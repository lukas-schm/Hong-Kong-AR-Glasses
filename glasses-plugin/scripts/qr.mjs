/* Print a QR code for sideloading the plugin into the Even App.
   Bakes the LAN-reachable CDARS server URL into the link as ?server=…,
   which src/config.ts persists on first load. */
import { networkInterfaces } from 'node:os';
import qrcode from 'qrcode-terminal';

function lanIp() {
  for (const ifaces of Object.values(networkInterfaces())) {
    for (const i of ifaces ?? []) {
      if (i.family === 'IPv4' && !i.internal) return i.address;
    }
  }
  return 'localhost';
}

const ip = lanIp();
const pluginPort = process.env.PLUGIN_PORT ?? '5173';
const apiPort = process.env.CDARS_PORT ?? '8002';
const url = `http://${ip}:${pluginPort}/?server=${encodeURIComponent(`http://${ip}:${apiPort}`)}`;

console.log(`\nSideload URL: ${url}\n`);
qrcode.generate(url, { small: true });
console.log('\nScan from the Even App (Even Hub → developer/sideload).');
console.log(`Make sure the CDARS API is listening on 0.0.0.0:${apiPort}.`);
