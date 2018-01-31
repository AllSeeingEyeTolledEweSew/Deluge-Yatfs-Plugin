import base64
import logging

from deluge import component
from deluge._libtorrent import lt
from deluge.core.rpcserver import export
from deluge.event import DelugeEvent
from deluge.plugins.pluginbase import CorePluginBase


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


class Core(CorePluginBase):

    def enable(self):
        self.torrent_to_piece_priority_maps = {}
        self.torrent_to_keep_redundant_connections_map = {}
        self.torrent_to_piece_to_data = {}

        self.core = component.get("Core")
        self.session = self.core.session
        self.torrents = self.core.torrentmanager.torrents
        self.pluginmanager = component.get("CorePluginManager")
        self.eventmanager = component.get("EventManager")
        self.alertmanager = component.get("AlertManager")

        self.alertmanager.register_handler(
            "read_piece_alert", self.on_read_piece)

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

    def disable(self):
        self.alertmanager.deregister_handler(self.on_read_piece)

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

    def update(self):
        pass

    def apply_piece_priorities(self, torrent_id):
        torrent = self.torrents.get(torrent_id)
        if torrent is None:
            return
        num_pieces = torrent.get_status(("num_pieces",)).get("num_pieces", 0)
        if not num_pieces:
            return
        priority_maps = list(
            self.torrent_to_piece_priority_maps.get(torrent_id, {}).values())
        priority_map = {}
        for i in range(num_pieces):
            p = -1
            for m in priority_maps:
                v = -1
                if type(m) is dict:
                    v = m.get(i)
                    if type(v) is not int:
                        v = -1
                elif type(m) is int:
                    v = m
                p = max(p, v)
            if p >= 0:
                priority_map[i] = p
        torrent.handle.prioritize_pieces(list(priority_map.items()))

    def apply_keep_redundant_connections(self, torrent_id):
        torrent = self.torrents.get(torrent_id)
        if torrent is None:
            return
        m = self.torrent_to_keep_redundant_connections_map.get(torrent_id, {})
        keep = any(m.values())
        torrent.handle.set_keep_redundant_connections(keep)

    def on_torrent_add(self, torrent_id):
        if torrent_id not in self.torrent_to_piece_priority_maps:
            self.torrent_to_piece_priority_maps[torrent_id] = {}
        else:
            self.apply_piece_priorities(torrent_id)

        if torrent_id not in self.torrent_to_keep_redundant_connections_map:
            self.torrent_to_keep_redundant_connections_map[torrent_id] = {}
        else:
            self.apply_keep_redundant_connections(torrent_id)

        self.torrent_to_piece_to_data[torrent_id] = {}

    def on_torrent_remove(self, torrent_id):
        self.torrent_to_piece_priority_maps.pop(torrent_id, {})
        self.torrent_to_keep_redundant_connections_map.pop(torrent_id, {})
        self.torrent_to_piece_to_data.pop(torrent_id, None)

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
