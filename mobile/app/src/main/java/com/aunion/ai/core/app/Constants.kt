package com.aunion.ai.core.app

import com.aunion.ai.BuildConfig

object Constants {
    // WebView URL (build.gradle.kts에서 설정)
    const val BASE_URL = BuildConfig.BASE_URL

    // 수강자 시작 페이지 (앱 기본 URL)
    const val STUDENT_START_URL = "$BASE_URL/#/student/start"

    // 다운로드 관련
    const val DOWNLOAD_CHANNEL_ID = "aunion_download"
    const val DOWNLOAD_CHANNEL_NAME = "Downloads"
}
