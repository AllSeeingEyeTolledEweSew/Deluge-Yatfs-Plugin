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
# This file is part of YATFS and is licensed under GNU General Public License 3.0, or later, with
# the additional special exception to link portions of this program with the OpenSSL library.
# See LICENSE for more details.
#

from deluge.plugins.init import PluginInitBase


class CorePlugin(PluginInitBase):
    def __init__(self, plugin_name):
        from core import Core as PluginClass
        self._plugin_cls = PluginClass
        super(CorePlugin, self).__init__(plugin_name)
