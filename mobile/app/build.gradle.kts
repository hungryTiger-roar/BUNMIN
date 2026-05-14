plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.hilt)
    alias(libs.plugins.ksp)
}

android {
    namespace = "com.aunion.ai"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.aunion.ai"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // WebView 가 붙을 강사 PC 주소. gradle.properties (또는 ~/.gradle/gradle.properties,
        // -PappBaseHost=... -PappBasePort=... CLI) 로 오버라이드. 개인 IP 를 build.gradle 에
        // 박지 말 것 — 팀원마다 LAN IP 다르고 강의실마다 또 다름.
        val appBaseHost = (project.findProperty("appBaseHost") as String?) ?: "10.0.2.2"
        val appBasePort = (project.findProperty("appBasePort") as String?) ?: "43000"
        buildConfigField("String", "BASE_URL", "\"http://$appBaseHost:$appBasePort\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
        debug {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    // Core
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.viewmodel.compose)

    // Compose
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.ui)
    implementation(libs.androidx.ui.graphics)
    implementation(libs.androidx.ui.tooling.preview)
    implementation(libs.androidx.material3)

    // Navigation
    implementation(libs.androidx.navigation.compose)

    // Hilt
    implementation(libs.hilt.android)
    ksp(libs.hilt.compiler)
    implementation(libs.hilt.navigation.compose)

    // WebView
    implementation(libs.androidx.webkit)

    // Debug
    debugImplementation(libs.androidx.ui.tooling)
}
