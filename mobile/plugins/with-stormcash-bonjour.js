// expo-nearby-connections' plugin replaces NSBonjourServices with only `_<name>._tcp`.
// Multipeer needs both the _tcp and _udp entries (spec §6.2), so add them back last.
const { withInfoPlist } = require('expo/config-plugins');

module.exports = function withStormcashBonjour(config) {
  return withInfoPlist(config, (c) => {
    const services = new Set(c.modResults.NSBonjourServices ?? []);
    services.add('_stormcash._tcp');
    services.add('_stormcash._udp');
    c.modResults.NSBonjourServices = [...services];
    return c;
  });
};
