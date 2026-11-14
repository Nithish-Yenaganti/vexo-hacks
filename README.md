# Grab the Screen

Pick up your phone with the hand wearing a Vexo Open band and twist. The laptop pauses its demo video and the phone resumes from the same position. Vexo connects to the laptop over Bluetooth. The phone sends its own gyroscope readings over Wi-Fi.

## Run it

Requires Node.js 20+, OpenSSL, Chrome or Edge on the laptop, and a phone with a gyroscope. Start the server from the repo:

```sh
node server.js
```

1. Open [localhost:8787](http://localhost:8787) in Chrome or Edge on the laptop. Double-tap the Vexo band, click **Pair band**, and select your **Vexo-HACK-XX**.
2. Open the full phone setup link shown on the laptop in iPhone Safari. Follow the steps to trust the demo's local certificate, open the HTTPS receiver, and tap **Enable motion**.
3. When the laptop says **Receiving motion**, start playback on the laptop. Hold the phone firmly with your band hand, give it a quick twist and return it, then hold still. If Safari asks for a tap to play, use **Play on phone**.
4. Use **Reset handoff** between attempts. For a negative control, have someone else twist the phone while you keep your band still.

If Safari cannot open the setup page on shared Wi-Fi, enable Personal Hotspot on the iPhone and connect the Mac to it. The setup link updates when the Mac changes networks. If the server selects the wrong Wi-Fi interface, set `PHONE_HOST` to the laptop's address on the shared network and restart. Use the new receiver link after restarting.

The setup uses a local CA generated in the ignored `tmp/tls` directory. Install only the profile from this laptop. On iPhone, remove the demo profile from **Settings → General → VPN & Device Management** when you finish. If Safari requires muted autoplay, tap **Unmute podcast** after the handoff.

The demo includes an 80-second excerpt of [NASA’s Curious Universe: Why Roman Will Make Unexpected Discoveries](https://svs.gsfc.nasa.gov/15082/), credited to NASA’s Goddard Space Flight Center.

## Implementation

The server keeps recent rotation samples and the handoff timestamp in memory. The laptop compares the phone and band rotation-speed traces with a short timing tolerance. This is a motion match, and the threshold still needs calibration on real hardware.

Run `node --test` for the motion-matching checks. The [Vexo Open Kit](https://github.com/VexoAI-Org/vexo-open-kit) JavaScript SDK is vendored at revision `1e4291e2fa4896b1f603d3d4f0b009c483425da0` under its included MIT license.
