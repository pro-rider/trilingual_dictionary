package com.example.trilingual_dictionary

import android.content.pm.ApplicationInfo
import android.os.Bundle
import android.view.WindowManager
import io.flutter.embedding.android.FlutterActivity

class MainActivity : FlutterActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // FLAG_SECURE keeps the app out of screenshots, screen recordings and the
        // recents thumbnail. It was applied unconditionally before, which is why
        // `adb screencap` returned an all-black frame even on a debug build and
        // why evidence could not be collected from the device.
        //
        // It is a real protection for account screens, so it is kept - but only
        // where it belongs: release builds. A debug build stays capturable, which
        // is what device verification and Play listing screenshots use (debug,
        // profile, or an emulator).
        //
        // TODO(auth-hardening): replace this whole-window flag with a per-screen
        // toggle (method channel) covering only auth, code, password and session
        // screens, so ordinary dictionary pages can be screenshotted in release
        // too. Tracked in docs/HUMAN_TODO.md.
        val debuggable = (applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0
        if (!debuggable) {
            window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        }
    }
}
