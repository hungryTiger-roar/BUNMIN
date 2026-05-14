package com.aunion.ai.core.app

import com.aunion.ai.BuildConfig

object Constants {
    // WebView URL (build.gradle.kts 의 appBaseHost / appBasePort 로 구성)
    const val BASE_URL = BuildConfig.BASE_URL

    // 다운로드 관련
    const val DOWNLOAD_CHANNEL_ID = "aunion_download"
    const val DOWNLOAD_CHANNEL_NAME = "Downloads"
}
