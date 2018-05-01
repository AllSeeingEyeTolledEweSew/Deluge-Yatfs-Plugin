import base64
import copy
import logging
import os
import threading

from deluge import component
from deluge._libtorrent import lt
import deluge.configmanager
from deluge.core.rpcserver import export
from deluge.event import DelugeEvent
from deluge.plugins.pluginbase import CorePluginBase
try:
    import rencode
except ImportError:
    import deluge.rencode as rencode


log = logging.getLogger(__name__)


def bool_list_to_bitfield(pieces):
    bvals = []
    for i in range(0, (len(pieces) - 1) / 8 + 1):
        b = 0
        for j, p in enumerate(pieces[i * 8:(i + 1) * 8]):
            if p:
                b |= 0x80 >> j
        bvals.append(b)
    return b"".join(chr(b) for b in bvals)


class YatfsReadPieceEvent(DelugeEvent):

    def __init__(self, torrent_id, piece, data, error):
        self._args = [torrent_id, piece, data, error]



class CacheFlushedEvent(DelugeEvent):

    def __init__(self, torrent_id):
        self._args = [torrent_id]



class StateWriter(threading.Thread):

    def __init__(self, path, **kwargs):
        super(StateWriter, self).__init__(**kwargs)

        self.cv = threading.Condition()
        self.done = False
        self.data = None
        self.path = path

    def set_data(self, data):
        with self.cv:
            self.data = data
            self.cv.notifyAll()

    def set_done(self):
        with self.cv:
            self.done = True
            self.cv.notifyAll()

    def step(self):
        with self.cv:
            while self.data is None and not self.done:
                self.cv.wait()
            if self.done:
                return True
            data = self.data
            self.data = None

        try:
            with open(self.path, mode="wb") as f:
                f.write(rencode.dumps(data))
        except:
            log.exception("While writing state")

    def run(self):
        while True:
            done = self.step()
            if done:
                break


class Core(CorePluginBase):

    def enable(self):
        self.core = component.get("Core")
        self.session = self.core.session
        self.torrents = self.core.torrentmanager.torrents
        self.pluginmanager = component.get("CorePluginManager")
        self.eventmanager = component.get("EventManager")
        self.alertmanager = component.get("AlertManager")

        self.alertmanager.register_handler(
            "read_piece_alert", self.on_read_piece)
        self.alertmanager.register_handler(
            "cache_flushed_alert", self.on_cache_flushed)

        self.eventmanager.register_event_handler(
            "TorrentAddedEvent", self.on_torrent_add)
        self.eventmanager.register_event_handler(
            "TorrentRemovedEvent", self.on_torrent_remove)

        self.pluginmanager.register_status_field(
            "yatfsrpc.piece_bitfield", self.get_piece_bitfield)
        self.pluginmanager.register_status_field(
            "yatfsrpc.sequential_download", self.get_sequential_download)
        self.pluginmanager.register_status_field(
            "yatfsrpc.piece_priority_map", self.get_piece_priority_map)
        self.pluginmanager.register_status_field(
            "yatfsrpc.keep_redundant_connections_map",
            self.get_keep_redundant_connections_map)
        self.pluginmanager.register_status_field(
            "yatfsrpc.piece_priorities", self.get_piece_priorities)
        self.pluginmanager.register_status_field(
            "yatfsrpc.cache_info", self.get_cache_info)

        state_path = os.path.join(
            deluge.configmanager.get_config_dir(), "yatfs.rencode")
        self.state_writer = StateWriter(
            state_path, name="yatfsrpc-state-writer")
        self.state_writer.daemon = True
        self.state_writer.start()

        if not hasattr(self, "torrent_to_piece_priority_maps"):
            try:
                with open(state_path, mode="rb") as f:
                    self.torrent_to_piece_priority_maps = rencode.loads(
                        f.read())
            except:
                log.exception("While reading %s", state_path)
                self.torrent_to_piece_priority_maps = {}

        self.torrent_to_keep_redundant_connections_map = {}
        self.torrent_to_piece_to_data = {}


    def disable(self):
        self.alertmanager.deregister_handler(self.on_read_piece)
        self.alertmanager.deregister_handler(self.on_cache_flushed)

        self.eventmanager.deregister_event_handler(
            "TorrentAddedEvent", self.on_torrent_add)
        self.eventmanager.deregister_event_handler(
            "TorrentRemovedEvent", self.on_torrent_remove)

        self.pluginmanager.deregister_status_field("yatfsrpc.piece_bitfield")
        self.pluginmanager.deregister_status_field(
            "yatfsrpc.sequential_download")
        self.pluginmanager.deregister_status_field(
            "yatfsrpc.piece_priority_map")
        self.pluginmanager.deregister_status_field(
            "yatfsrpc.keep_redundant_connections_map")
        self.pluginmanager.deregister_status_field("yatfsrpc.piece_priorities")
        self.pluginmanager.deregister_status_field("yatfsrpc.cache_info")

        self.state_writer.set_done()

    def update(self):
        pass

    def save_state(self):
        self.state_writer.set_data(
            copy.deepcopy(self.torrent_to_piece_priority_maps))

    def apply_piece_priorities(self, torrent_id):
        torrent = self.torrents.get(torrent_id)
        if torrent is None:
            return
        num_pieces = torrent.get_status(("num_pieces",)).get("num_pieces", 0)
        if not num_pieces:
            return
        priority_maps = self.torrent_to_piece_priority_maps.get(torrent_id, {})
        have = torrent.handle.status(lt.status_flags_t.query_pieces).pieces
        priority_map = {}
        for i in range(num_pieces):
            p = -1
            for k, m in list(priority_maps.items()):
                v = -1
                if type(m) is dict:
                    if have[i]:
                        m.pop(i, None)
                    else:
                        v = m.get(i)
                        if type(v) is not int:
                            m.pop(i, None)
                            v = -1
                    if not m:
                        priority_maps.pop(k, None)
                elif type(m) is int:
                    v = m
                else:
                    priority_maps.pop(k, None)
                p = max(p, v)
            if p >= 0:
                priority_map[i] = p
        if all(have) or not priority_maps:
            self.torrent_to_piece_priority_maps.pop(torrent_id, None)
        torrent.handle.prioritize_pieces(list(priority_map.items()))

    def apply_keep_redundant_connections(self, torrent_id):
        torrent = self.torrents.get(torrent_id)
        if torrent is None:
            return
        m = self.torrent_to_keep_redundant_connections_map.get(torrent_id, {})
        keep = any(m.values())
        torrent.handle.set_keep_redundant_connections(keep)

    def on_torrent_add(self, torrent_id):
        if torrent_id not in self.torrent_to_keep_redundant_connections_map:
            self.torrent_to_keep_redundant_connections_map[torrent_id] = {}
        else:
            self.apply_keep_redundant_connections(torrent_id)

        if torrent_id in self.torrent_to_piece_priority_maps:
            self.apply_piece_priorities(torrent_id)

        self.torrent_to_piece_to_data[torrent_id] = {}

    def on_torrent_remove(self, torrent_id):
        self.torrent_to_piece_priority_maps.pop(torrent_id, {})
        self.torrent_to_keep_redundant_connections_map.pop(torrent_id, {})
        self.torrent_to_piece_to_data.pop(torrent_id, None)
        self.save_state()

    @export
    def update_piece_priority_map(self, torrent_id, update=None, delete=None):
        if torrent_id not in self.torrent_to_piece_priority_maps:
            self.torrent_to_piece_priority_maps[torrent_id] = {}
        m = self.torrent_to_piece_priority_maps[torrent_id]
        if update:
            m.update(update)
        for k in (delete or []):
            m.pop(k, None)
        self.apply_piece_priorities(torrent_id)
        self.save_state()

    @export
    def update_keep_redundant_connections_map(self, torrent_id, update=None,
            delete=None):
        if torrent_id not in self.torrent_to_keep_redundant_connections_map:
            self.torrent_to_keep_redundant_connections_map[torrent_id] = {}
        m = self.torrent_to_keep_redundant_connections_map[torrent_id]
        if update:
            m.update(update)
        for k in (delete or []):
            m.pop(k, None)
        self.apply_keep_redundant_connections(torrent_id)

    def get_piece_priority_map(self, torrent_id):
        return self.torrent_to_piece_priority_maps.get(torrent_id, {})

    def get_keep_redundant_connections_map(self, torrent_id):
        return self.torrent_to_keep_redundant_connections_map.get(
            torrent_id, {})

    def get_piece_bitfield(self, torrent_id):
        torrent = self.torrents[torrent_id]
        status = torrent.handle.status(lt.status_flags_t.query_pieces)
        return bool_list_to_bitfield(status.pieces)

    def get_sequential_download(self, torrent_id):
        torrent = self.torrents[torrent_id]
        return torrent.status.sequential_download

    def get_cache_info(self, torrent_id, flags=0):
        torrent = self.torrents[torrent_id]
        cache_status = self.session.get_cache_info(torrent.handle, flags)
        ret = {}
        for key in dir(cache_status):
            if key.startswith("_"):
                continue
            ret[key] = getattr(cache_status, key)
        return ret

    @export
    def set_sequential_download(self, torrent_id, sequential_download):
        torrent = self.torrents[torrent_id]
        torrent.handle.set_sequential_download(sequential_download)

    @export
    def session_get_settings(self, keys):
        ret = {}
        settings = self.session.settings()
        for key in keys:
            ret[key] = getattr(settings, key)
        return ret

    @export
    def session_set_settings(self, **kwargs):
        settings = self.session.settings()
        for k, v in kwargs.items():
            setattr(settings, k, v)
        self.session.set_settings(settings)

    @export
    def read_piece(self, torrent_id, piece):
        if piece in self.torrent_to_piece_to_data[torrent_id]:
            return
        self.torrent_to_piece_to_data[torrent_id][piece] = None
        return self.torrents[torrent_id].handle.read_piece(piece)

    @export
    def flush_cache(self, torrent_id):
        return self.torrents[torrent_id].handle.flush_cache()

    def get_piece_priorities(self, torrent_id):
        torrent = self.torrents[torrent_id]
        return torrent.handle.piece_priorities()

    def emit_read_piece_events(self, torrent_id):
        piece_to_data = self.torrent_to_piece_to_data[torrent_id]
        pieces = sorted(piece_to_data.keys())
        for piece in pieces:
            what = piece_to_data[piece]
            if what is None:
                break
            data, error = what
            self.eventmanager.emit(
                YatfsReadPieceEvent(torrent_id, piece, data, error))
            del piece_to_data[piece]

    def on_read_piece(self, alert):
        log.debug("yatfsrpc.on_read_piece")
        try:
            torrent_id = str(alert.handle.info_hash())
            piece = alert.piece
            data = alert.buffer
            e = alert.ec
            error = {"message": e.message(), "value": e.value()}
            self.torrent_to_piece_to_data[torrent_id][piece] = (data, error)
            self.emit_read_piece_events(torrent_id)
        except:
            log.exception("yatfsrpc.on_read_piece")
            raise

    def on_cache_flushed(self, alert):
        torrent_id = str(alert.handle.info_hash())
        self.eventmanager.emit(CacheFlushedEvent(torrent_id))
