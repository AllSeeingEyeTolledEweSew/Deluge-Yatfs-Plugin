#
# -*- coding: utf-8 -*-#

# Copyright (C) 2016 AllSeeingEyeTolledEweSew <allseeingeyetolledewesew@protonmail.com>
#
# Basic plugin template created by:
# Copyright (C) 2008 Martijn Voncken <mvoncken@gmail.com>
# Copyright (C) 2007-2009 Andrew Resch <andrewresch@gmail.com>
# Copyright (C) 2009 Damien Churchill <damoxc@gmail.com>
# Copyright (C) 2010 Pedro Algarvio <pedro@algarvio.me>
#
# This file is part of PieceIO and is licensed under GNU General Public License 3.0, or later, with
# the additional special exception to link portions of this program with the OpenSSL library.
# See LICENSE for more details.
#

import base64
import logging

from deluge import component
from deluge._libtorrent import lt
from deluge.core.rpcserver import export
from deluge.event import DelugeEvent
from deluge.plugins.pluginbase import CorePluginBase


log = logging.getLogger(__name__)


def piece_bitstring(pieces):
    bvals = []
    for i in range(0, (len(pieces) - 1) / 8 + 1):
        b = 0
        for j, p in enumerate(pieces[i * 8:(i + 1) * 8]):
            if p:
                b |= 0x80 >> j
        bvals.append(b)
    return base64.b64encode("".join(chr(b) for b in bvals))


class ReadPieceEvent(DelugeEvent):

    def __init__(self, torrent_id, piece, buf):
        self._args = [torrent_id, piece, buf]


class CacheFlushedEvent(DelugeEvent):

    def __init__(self, torrent_id, pieces):
        self._args = [torrent_id, pieces]


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

        self.pluginmanager.register_status_field(
            "pieces", self.get_pieces)
        self.pluginmanager.register_status_field(
            "piece_bitstring", self.get_piece_bitstring)
        self.pluginmanager.register_status_field(
            "piece_priorities", self.get_piece_priorities)
        self.pluginmanager.register_status_field(
            "sequential_download", self.get_sequential_download)

    def disable(self):
        self.alertmanager.deregister_handler(self.on_read_piece)
        self.alertmanager.deregister_handler(self.on_cache_flushed)

        self.pluginmanager.deregister_status_field("pieces")
        self.pluginmanager.deregister_status_field("piece_bitstring")
        self.pluginmanager.deregister_status_field("piece_priorities")
        self.pluginmanager.deregister_status_field("sequential_download")

    def update(self):
        pass

    @export
    def get_pieces(self, torrent_id):
        torrent = self.torrents[torrent_id]
        status = torrent.handle.status(lt.status_flags_t.query_pieces)
        return [1 if p else 0 for p in status.pieces]

    @export
    def get_piece_bitstring(self, torrent_id):
        torrent = self.torrents[torrent_id]
        status = torrent.handle.status(lt.status_flags_t.query_pieces)
        return piece_bitstring(status.pieces)

    @export
    def get_piece_priorities(self, torrent_id):
        torrent = self.torrents[torrent_id]
        return torrent.handle.piece_priorities()

    @export
    def get_sequential_download(self, torrent_id):
        torrent = self.torrents[torrent_id]
        return torrent.status.sequential_download

    def on_read_piece(self, alert):
        torrent_id = str(alert.handle.info_hash())
        piece = alert.piece
        buf = alert.buffer[:alert.size]
        self.eventmanager.emit(ReadPieceEvent(torrent_id, piece, buf))

    def on_cache_flushed(self, alert):
        torrent_id = str(alert.handle.info_hash())
        if hasattr(alert, "pieces"):
            pieces = piece_bitstring(alert.pieces)
        else:
            pieces = None
        self.eventmanager.emit(CacheFlushedEvent(torrent_id, pieces))

    @export
    def set_sequential_download(self, torrent_id, sequential_download):
        torrent = self.torrents[torrent_id]
        torrent.handle.set_sequential_download(sequential_download)

    @export
    def read_piece(self, torrent_id, piece):
        torrent = self.torrents[torrent_id]
        torrent.handle.read_piece(piece)

    @export
    def set_piece_deadline(self, torrent_id, piece, deadline, flags):
        torrent = self.torrents[torrent_id]
        torrent.handle.set_piece_deadline(piece, deadline, flags)

    @export
    def reset_piece_deadline(self, torrent_id, piece):
        torrent = self.torrents[torrent_id]
        torrent.handle.reset_piece_deadline(piece)

    @export
    def set_piece_priority(self, torrent_id, piece, priority):
        torrent = self.torrents[torrent_id]
        torrent.handle.piece_priority(piece, priority)

    @export
    def prioritize_pieces(self, torrent_id, priorities):
        torrent = self.torrents[torrent_id]
        torrent.handle.prioritize_pieces(priorities)

    @export
    def flush_cache(self, torrent_id):
        torrent = self.torrents[torrent_id]
        torrent.handle.flush_cache()
