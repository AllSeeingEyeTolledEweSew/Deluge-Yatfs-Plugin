from deluge.plugins.init import PluginInitBase


class CorePlugin(PluginInitBase):
    def __init__(self, plugin_name):
        from core import Core as PluginClass
        self._plugin_cls = PluginClass
        super(CorePlugin, self).__init__(plugin_name)
