# Aunion AI Mobile App

Android WebView 기반 수강자용 모바일 앱

## 프로젝트 개요

- **플랫폼**: Android (minSdk 26, targetSdk 34)
- **아키텍처**: MVVM + Clean Architecture
- **UI**: Jetpack Compose
- **DI**: Hilt
- **기능**: WebView 래퍼 앱 (React 프론트엔드를 네이티브 앱으로 감싸는 형태)

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| URL 입력 화면 | 강의자가 공유한 URL 입력 (마지막 URL 저장, `http://` 자동 추가) |
| 전체화면 모드 | 강의 화면에서 상태바/네비게이션바 숨김 |
| 가로 모드 고정 | 강의 화면 진입 시 자동으로 가로 모드 전환 |
| 파일 업로드 | 이미지/파일 선택 지원 (SAF 기반) |
| 마이크/카메라 권한 | VAD, 음성인식용 (필요 리소스만 허용) |
| 파일 다운로드 | DownloadManager + 쿠키 세션 유지 |
| 뒤로가기 | WebView 히스토리 네비게이션 |

---

## 프로젝트 구조

```
mobile/
├── build.gradle.kts              # 루트 빌드 설정
├── settings.gradle.kts           # 프로젝트 설정
├── gradle.properties             # Gradle 속성
├── local.properties              # 로컬 SDK 경로 (Git 제외)
├── gradlew / gradlew.bat         # Gradle Wrapper
│
├── gradle/
│   ├── wrapper/
│   │   ├── gradle-wrapper.jar
│   │   └── gradle-wrapper.properties
│   └── libs.versions.toml        # 버전 카탈로그 (의존성 관리)
│
└── app/
    ├── build.gradle.kts          # 앱 모듈 빌드 설정
    ├── proguard-rules.pro        # ProGuard 난독화 규칙
    │
    └── src/main/
        ├── AndroidManifest.xml   # 앱 매니페스트
        │
        ├── java/com/aunion/ai/
        │   │
        │   ├── MainActivity.kt   # 메인 액티비티 (앱 진입점)
        │   │
        │   ├── core/             # 핵심 모듈
        │   │   ├── app/
        │   │   │   └── AunionApplication.kt  # Application 클래스 (@HiltAndroidApp)
        │   │   └── di/
        │   │       └── AppModule.kt          # Hilt 의존성 주입 모듈
        │   │
        │   ├── data/             # 데이터 레이어
        │   │   └── download/
        │   │       └── DownloadRepository.kt # 파일 다운로드 처리
        │   │
        │   └── ui/               # UI 레이어
        │       ├── theme/
        │       │   ├── Color.kt      # 색상 정의
        │       │   ├── Theme.kt      # 테마 설정
        │       │   └── Type.kt       # 타이포그래피
        │       │
        │       ├── navigation/
        │       │   └── NavGraph.kt   # 네비게이션 그래프
        │       │
        │       └── screens/
        │           ├── url/
        │           │   └── UrlInputScreen.kt    # URL 입력 화면
        │           └── webview/
        │               ├── WebViewScreen.kt      # WebView 화면
        │               └── WebViewViewModel.kt   # WebView 상태 관리
        │
        └── res/
            ├── values/
            │   ├── strings.xml   # 문자열 리소스
            │   ├── colors.xml    # 색상 리소스
            │   └── themes.xml    # 테마 리소스
            ├── values-night/
            │   └── themes.xml    # 다크모드 테마
            ├── xml/
            │   └── file_paths.xml # FileProvider 경로
            ├── drawable/
            │   └── ic_launcher_foreground.xml  # 앱 아이콘 전경
            └── mipmap-*/         # 앱 아이콘 (해상도별)
```

---

## 앱 실행 흐름

### 1. 앱 시작
```
사용자가 앱 아이콘 터치
    ↓
AunionApplication 초기화 (Hilt DI 설정)
    ↓
MainActivity 실행
    ↓
NavGraph 로드 (startDestination = UrlInput)
```

### 2. URL 입력 화면
```
UrlInputScreen 표시
    - "Aunion AI" 타이틀
    - "수강자 앱" 서브타이틀
    - URL 입력 필드 (마지막 입력 URL 자동 복원)
    - X 버튼으로 URL 삭제 가능
    - "강의 참여" 버튼
    ↓
URL 입력 후 "강의 참여" 버튼 터치
    ↓
WebViewScreen으로 네비게이션
```

### 3. WebView 화면 (강의 화면)
```
WebViewScreen 로드
    ↓
전체화면 + 가로모드 전환
    - 상태바 숨김
    - 네비게이션바 숨김
    - 가로 모드 고정
    ↓
WebView 초기화
    - JavaScript 활성화
    - DOM Storage 활성화
    - Mixed Content 허용
    - 100vh CSS 자동 수정 (모바일 WebView 호환)
    ↓
입력한 URL 로드
    ↓
React 프론트엔드 표시 (수강자 강의 화면)
```

---

## WebView 설정 상세

```kotlin
settings.apply {
    // JavaScript 및 DOM Storage
    javaScriptEnabled = true
    domStorageEnabled = true
    databaseEnabled = true

    // Mixed Content - DEBUG에서만 HTTP 혼합 허용
    mixedContentMode = if (BuildConfig.DEBUG) {
        WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
    } else {
        WebSettings.MIXED_CONTENT_NEVER_ALLOW
    }

    // 파일 접근 - SAF 기반 업로드용
    allowFileAccess = true
    allowContentAccess = true  // content:// URI 접근 (SAF)
    allowFileAccessFromFileURLs = false
    allowUniversalAccessFromFileURLs = false

    // 기타
    mediaPlaybackRequiresUserGesture = false
    javaScriptCanOpenWindowsAutomatically = true
}
```

### 보안 설정
- **Mixed Content**: DEBUG 빌드에서만 HTTP+HTTPS 혼합 허용 (내부망 테스트용)
- **파일 접근**: `allowContentAccess`로 SAF의 `content://` URI 허용, 파일 URL 간 접근은 차단
- **WebView 권한**: 마이크/카메라만 허용, 다른 리소스 요청은 거부

### 100vh CSS 수정
모바일 WebView에서 `100vh`가 제대로 작동하지 않는 문제를 해결하기 위해 CSS 변수 방식을 사용합니다:
- `--app-height`, `--app-width` CSS 변수로 실제 뷰포트 크기 설정
- React 레이아웃과 충돌 없이 동작
- resize 이벤트에 반응하여 자동 업데이트

---

## 권한

### AndroidManifest.xml

```xml
<!-- 네트워크 -->
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />

<!-- 알림 (Android 13+) -->
<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />

<!-- 마이크 (VAD, 음성인식) -->
<uses-permission android:name="android.permission.RECORD_AUDIO" />
<uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />

<!-- 카메라 (선택적) -->
<uses-permission android:name="android.permission.CAMERA" />
```

> **참고**: 파일 업로드는 SAF(Storage Access Framework), 다운로드는 DownloadManager를 사용하므로
> targetSdk 34 기준 `WRITE_EXTERNAL_STORAGE`, `READ_EXTERNAL_STORAGE` 권한은 불필요합니다.

### Application 설정

```xml
<application
    android:name=".core.app.AunionApplication"
    android:usesCleartextTraffic="true"
    android:theme="@style/Theme.AunionAI"
    ... >
</application>
```

---

## 빌드 및 실행

### 요구사항
- Android Studio Hedgehog 이상
- JDK 17
- Android SDK 34

### 빌드
```bash
cd mobile
./gradlew assembleDebug
```

### 설치 (디버그)
```bash
./gradlew installDebug
```

### APK 위치
```
app/build/outputs/apk/debug/app-debug.apk
```

---

## 화면 미리보기

### 1. URL 입력 화면
```
┌─────────────────────┐
│                     │
│      Aunion AI      │  ← 타이틀
│       수강자 앱      │  ← 서브타이틀
│                     │
│  ┌───────────────┐  │
│  │ URL 입력    ✕ │  │  ← URL 입력 필드 + 삭제 버튼
│  └───────────────┘  │
│                     │
│  ┌───────────────┐  │
│  │   강의 참여    │  │  ← 참여 버튼
│  └───────────────┘  │
│                     │
│ 강의자가 공유한 URL  │
│    을 입력하세요     │
│                     │
└─────────────────────┘
```

### 2. 강의 화면 (WebView, 가로 전체화면)
```
┌─────────────────────────────────────────────┐
│                                             │
│                                             │
│            React 프론트엔드                  │
│            수강자 강의 화면                  │
│         (슬라이드 + 번역 자막)               │
│                                             │
│                                             │
└─────────────────────────────────────────────┘
         전체화면 (시스템 바 숨김)
```

---

## 주의사항

1. **local.properties는 Git에 올리지 마세요** (.gitignore에 포함)
2. **휴대폰과 서버 PC가 같은 네트워크**에 있어야 함
3. **PC 방화벽**에서 서버 포트 허용 필요
4. **화면 나갈 때** 자동으로 세로 모드 + 시스템 바 복원
5. **URL에 `localhost` 사용 금지** - 서버 내부 IP (192.168.x.x) 사용

### 내부망 HTTP 사용 안내
- 본 앱은 **내부 네트워크 시연 환경**을 기준으로 HTTP 접속을 허용합니다
- 실제 외부 배포 시에는 **HTTPS 적용** 및 Mixed Content 제한이 필요합니다

**HTTP 관련 설정 차이:**
| 설정 | 역할 |
|------|------|
| `usesCleartextTraffic="true"` | HTTP 페이지 접속 자체를 허용 |
| `mixedContentMode` | HTTPS 페이지 안에서 HTTP 리소스를 불러올 때의 정책 |

### URL 자동 보정
- 프로토콜이 없는 URL 입력 시 내부망 시연 기준으로 `http://`를 자동 추가합니다
- 예: `192.168.0.10:5173` → `http://192.168.0.10:5173`
- 외부 배포 시에는 `https://` 기본으로 변경 권장

---

## 향후 개선 사항

- [ ] 앱 아이콘 Aunion AI 로고로 변경
- [ ] 오프라인 에러 화면 추가
- [ ] 푸시 알림 (FCM) 연동
- [ ] 앱 업데이트 체크
