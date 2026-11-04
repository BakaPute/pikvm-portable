# Upstream KVMD 4.213 test fixture

Source: https://github.com/pikvm/kvmd/tree/v4.213 (tag v4.213).
Files under `web/` and `LICENSE` are upstream sources, unchanged, obtained
through the GitHub connector. `SHA256.json` records their bytes and is verified
by `tests/portable-native-4213.cjs`. Copyright and GPL-3.0-or-later notices are
preserved; see LICENSE. `user.css` is a local customization absent upstream;
the test serves an empty stylesheet for that URL.

The browser test loads the original HTML, styles, Msd, window manager, Keyboard,
Mouse and their dependencies. It substitutes the main bootstrap in the HTTP
response with `../native-kvm-4213.js` to supply synthetic telemetry, a video image
and a HID sink. The project's real `web/share/js/drive-folders.js` is loaded as
on the Pi. All HTTP mutations are intercepted and restricted to simulated MSD
selection/connection; no actual ISO or device is accessed.

This exercises native controller integration, not the full KVMD daemon,
streamer/WebSocket transport or physical USB host. Hardware acceptance remains
mandatory. These test assets are excluded from the Pi installation archive.
