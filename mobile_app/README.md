# RKL Mobile Client

This is a read-only Flutter client for the existing RKL service. It consumes `/api/v1/mobile/*` and `/api/v1/mobile/stream`; it does not contain signal, option-selection, order, fill, position, P&L, or execution logic.

## Local install

1. Install Flutter stable and Android Studio with an Android SDK/emulator.
2. From this directory run `flutter pub get`.
3. Start the existing RKL service in safe mode (`EXECUTION_MODE=READ_ONLY`, `REAL_ORDERS_ENABLED=OFF`).
4. Set a long random `MOBILE_API_TOKEN` in the backend `.env` and restart RKL.
5. For an Android emulator run:

```powershell
flutter run -d emulator-5554 --dart-define=RKL_API_BASE=http://10.0.2.2:8765 --dart-define=RKL_API_TOKEN=YOUR_TOKEN
```

For a physical device, use an HTTPS development tunnel or the machine's reachable HTTPS address. Do not expose port 8765 directly to the Internet.

## Themes

The client provides exactly four selectable terminal themes from Settings:

- RKL DARK: default premium dark terminal.
- RKL LIGHT: professional daytime terminal.
- RKL PRO: compact institutional/quant presentation.
- RKL NEON: restrained high-tech dark presentation.

The selected theme is stored locally on the device and applies immediately without restarting the app. No credentials or trading state are stored by the theme preference.

## Profile validation

```powershell
flutter pub get
flutter analyze
flutter test
flutter build apk --profile
flutter run --profile -d emulator-5554 --dart-define=RKL_API_BASE=http://10.0.2.2:8765 --dart-define=RKL_API_TOKEN=YOUR_TOKEN
```

Use the existing `MOBILE_API_TOKEN` only for `RKL_API_TOKEN`. Never use an Upstox access token in the mobile client.

## Release APK

```powershell
flutter build apk --release --dart-define=RKL_API_BASE=https://api.example.com --dart-define=RKL_API_TOKEN=DEVICE_SCOPED_TOKEN
```

Do not put a production master token in a public APK. The first client is a controlled internal build; production should use short-lived authenticated sessions issued by an HTTPS API gateway.

## Distribution

- Internal testing: distribute the signed APK through a private artifact store or Google Play internal testing.
- Client release: use Google Play closed testing, then production after authentication, TLS, authorization, audit logging, reconnect, and sandbox-isolation tests pass.
- For multiple users, replace the launch token with login/device registration and scoped short-lived tokens. The backend remains the source of truth.
