package com.example.trilingual_dictionary

import android.os.Bundle
import android.view.WindowManager
import io.flutter.embedding.android.FlutterActivity

class MainActivity : FlutterActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // FLAG_SECURE: no screenshots, no thumbnails in the recents switcher.
        // The account screens (and the offline dictionary, which is the user's
        // own data) must not show up in someone else's photo roll.
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
    }
}
