package com.aunion.ai.ui.screens.webview

import android.annotation.SuppressLint
import android.app.Activity
import android.content.pm.ActivityInfo
import android.graphics.Bitmap
import android.net.Uri
import android.os.Message
import android.webkit.ConsoleMessage
import android.webkit.GeolocationPermissions
import android.webkit.PermissionRequest
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceError
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.util.Log
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.hilt.navigation.compose.hiltViewModel
import com.aunion.ai.BuildConfig

private const val TAG = "WebViewScreen"

@SuppressLint("SetJavaScriptEnabled")
@Composable
fun WebViewScreen(
    url: String,
    viewModel: WebViewViewModel = hiltViewModel()
) {
    val context = LocalContext.current
    val uiState by viewModel.uiState.collectAsState()

    // WebView 인스턴스를 Composable 레벨에서 관리 (ViewModel에서 분리)
    var webViewInstance by remember { mutableStateOf<WebView?>(null) }

    // WebView 생명주기 정리
    DisposableEffect(Unit) {
        onDispose {
            webViewInstance?.let { webView ->
                webView.stopLoading()
                webView.destroy()
            }
            webViewInstance = null
        }
    }

    // ViewModel의 명령 관찰 및 WebView 제어
    LaunchedEffect(Unit) {
        viewModel.commands.collect { command ->
            when (command) {
                is WebViewCommand.GoBack -> {
                    webViewInstance?.let { webView ->
                        if (webView.canGoBack()) {
                            webView.goBack()
                        }
                    }
                }
            }
        }
    }

    // 가로 모드 고정 + 전체화면 모드
    DisposableEffect(Unit) {
        val activity = context as? Activity
        val originalOrientation = activity?.requestedOrientation

        // 가로 모드 고정
        activity?.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE

        // 전체화면 모드 (시스템 바 숨기기) - WindowCompat 사용
        activity?.window?.let { window ->
            WindowCompat.setDecorFitsSystemWindows(window, false)
            val controller = WindowInsetsControllerCompat(window, window.decorView)
            controller.hide(WindowInsetsCompat.Type.systemBars())
            controller.systemBarsBehavior = WindowInsetsControllerCompat.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
        }

        onDispose {
            // 화면을 나갈 때 원래 상태로 복원
            activity?.requestedOrientation = originalOrientation ?: ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED

            activity?.window?.let { window ->
                WindowCompat.setDecorFitsSystemWindows(window, true)
                val controller = WindowInsetsControllerCompat(window, window.decorView)
                controller.show(WindowInsetsCompat.Type.systemBars())
            }
        }
    }

    // 파일 업로드 콜백
    var fileUploadCallback by remember { mutableStateOf<ValueCallback<Array<Uri>>?>(null) }

    val fileChooserLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.GetMultipleContents()
    ) { uris ->
        fileUploadCallback?.onReceiveValue(uris.toTypedArray())
        fileUploadCallback = null
    }

    BackHandler(enabled = uiState.canGoBack) {
        viewModel.goBack()
    }

    Box(modifier = Modifier.fillMaxSize()) {
        AndroidView(
            factory = { context ->
                WebView(context).apply {
                    settings.apply {
                        // JavaScript 및 DOM Storage
                        javaScriptEnabled = true
                        domStorageEnabled = true
                        databaseEnabled = true

                        // Mixed Content 허용 - DEBUG에서만 허용 (내부망 HTTP 테스트용)
                        mixedContentMode = if (BuildConfig.DEBUG) {
                            WebSettings.MIXED_CONTENT_ALWAYS_ALLOW
                        } else {
                            WebSettings.MIXED_CONTENT_NEVER_ALLOW
                        }

                        // 캐시 설정
                        cacheMode = WebSettings.LOAD_DEFAULT

                        // 줌 비활성화 (강의 화면 고정)
                        setSupportZoom(false)
                        builtInZoomControls = false
                        displayZoomControls = false

                        // 뷰포트 설정
                        loadWithOverviewMode = false
                        useWideViewPort = false

                        // 파일 접근 - 보안 설정
                        allowFileAccess = true
                        allowContentAccess = true
                        @Suppress("DEPRECATION")
                        allowFileAccessFromFileURLs = false
                        @Suppress("DEPRECATION")
                        allowUniversalAccessFromFileURLs = false

                        // 미디어 자동재생 허용 (VAD 등에 필요)
                        mediaPlaybackRequiresUserGesture = false

                        // JavaScript에서 window.open 허용
                        javaScriptCanOpenWindowsAutomatically = true
                        setSupportMultipleWindows(false)

                        // 텍스트 인코딩
                        defaultTextEncodingName = "UTF-8"

                        // User Agent에 모바일 앱 정보 추가
                        userAgentString = "$userAgentString AunionAI-Mobile/1.0"
                    }

                    // 하드웨어 가속 사용
                    setLayerType(WebView.LAYER_TYPE_HARDWARE, null)

                    // 배경색 흰색
                    setBackgroundColor(android.graphics.Color.WHITE)

                    // 초기 스케일 100%로 강제
                    setInitialScale(100)

                    webViewClient = object : WebViewClient() {
                        override fun onPageStarted(view: WebView?, url: String?, favicon: Bitmap?) {
                            super.onPageStarted(view, url, favicon)
                            viewModel.updateLoadingState(true)
                            Log.d(TAG, "Page started: $url")
                        }

                        override fun onPageFinished(view: WebView?, url: String?) {
                            super.onPageFinished(view, url)
                            viewModel.updateLoadingState(false)
                            viewModel.updateCanGoBack(canGoBack())
                            Log.d(TAG, "Page finished: $url")

                            // WebView에서 100vh 문제 해결 - CSS 변수 방식 사용
                            val cssFixScript = """
                                (function() {
                                    function setAppHeight() {
                                        var vh = window.innerHeight;
                                        var vw = window.innerWidth;

                                        // CSS 변수로 실제 뷰포트 크기 설정
                                        document.documentElement.style.setProperty('--app-height', vh + 'px');
                                        document.documentElement.style.setProperty('--app-width', vw + 'px');

                                        console.log('[WebView] Set --app-height: ' + vh + 'px, --app-width: ' + vw + 'px');
                                    }

                                    // CSS 스타일 주입 (CSS 변수 사용)
                                    var style = document.getElementById('webview-vh-fix');
                                    if (!style) {
                                        style = document.createElement('style');
                                        style.id = 'webview-vh-fix';
                                        style.textContent = [
                                            ':root { --app-height: 100vh; --app-width: 100vw; }',
                                            'html, body { height: var(--app-height) !important; width: var(--app-width) !important; margin: 0 !important; padding: 0 !important; overflow: hidden !important; }',
                                            '#root { height: var(--app-height) !important; width: var(--app-width) !important; min-height: var(--app-height) !important; overflow: hidden !important; }',
                                            '.h-screen { height: var(--app-height) !important; min-height: var(--app-height) !important; }'
                                        ].join('\n');
                                        document.head.appendChild(style);
                                    }

                                    // 즉시 실행 + 지연 실행 (React 렌더링 대기)
                                    setAppHeight();
                                    setTimeout(setAppHeight, 100);
                                    setTimeout(setAppHeight, 500);
                                    setTimeout(setAppHeight, 1000);

                                    // resize 이벤트 처리
                                    window.addEventListener('resize', setAppHeight);
                                })();
                            """.trimIndent()
                            view?.evaluateJavascript(cssFixScript, null)
                        }

                        override fun shouldOverrideUrlLoading(
                            view: WebView?,
                            request: WebResourceRequest?
                        ): Boolean {
                            val url = request?.url?.toString() ?: return false

                            // 외부 링크 처리 (필요시)
                            // 현재는 모든 링크를 WebView 내에서 처리
                            return false
                        }

                        override fun onReceivedError(
                            view: WebView?,
                            request: WebResourceRequest?,
                            error: WebResourceError?
                        ) {
                            super.onReceivedError(view, request, error)
                            Log.e(TAG, "WebView error: ${error?.description}")
                        }
                    }

                    webChromeClient = object : WebChromeClient() {
                        override fun onProgressChanged(view: WebView?, newProgress: Int) {
                            super.onProgressChanged(view, newProgress)
                            viewModel.updateProgress(newProgress)
                        }

                        // 파일 업로드 처리
                        override fun onShowFileChooser(
                            webView: WebView?,
                            filePathCallback: ValueCallback<Array<Uri>>?,
                            fileChooserParams: FileChooserParams?
                        ): Boolean {
                            fileUploadCallback?.onReceiveValue(null)
                            fileUploadCallback = filePathCallback

                            val mimeTypes = fileChooserParams?.acceptTypes?.firstOrNull() ?: "*/*"
                            fileChooserLauncher.launch(mimeTypes)
                            return true
                        }

                        // 권한 요청 처리 (마이크, 카메라만 허용)
                        override fun onPermissionRequest(request: PermissionRequest?) {
                            request?.let { req ->
                                Log.d(TAG, "Permission request: ${req.resources.joinToString()}")

                                // 필요한 리소스만 허용 (마이크, 카메라)
                                val allowedResources = req.resources.filter { resource ->
                                    resource == PermissionRequest.RESOURCE_AUDIO_CAPTURE ||
                                    resource == PermissionRequest.RESOURCE_VIDEO_CAPTURE
                                }.toTypedArray()

                                if (allowedResources.isNotEmpty()) {
                                    req.grant(allowedResources)
                                } else {
                                    req.deny()
                                }
                            }
                        }

                        // 위치 권한 - 불필요하므로 거부
                        override fun onGeolocationPermissionsShowPrompt(
                            origin: String?,
                            callback: GeolocationPermissions.Callback?
                        ) {
                            callback?.invoke(origin, false, false)
                        }

                        // 콘솔 로그 (디버깅용)
                        override fun onConsoleMessage(consoleMessage: ConsoleMessage?): Boolean {
                            consoleMessage?.let {
                                Log.d(TAG, "[Console] ${it.messageLevel()}: ${it.message()} (${it.sourceId()}:${it.lineNumber()})")
                            }
                            return true
                        }

                        /**
                         * 새 창 처리 (target="_blank" 등)
                         *
                         * 설계 의도: 단일 WebView 화면 유지
                         * - 강의 시청 중 새 탭/창으로 이탈 방지
                         * - 전체화면 가로 모드 경험 유지
                         * - 새 창 URL을 현재 WebView에서 로드
                         *
                         * 향후 필요시 외부 브라우저 열기 옵션 추가 가능:
                         * Intent(Intent.ACTION_VIEW, Uri.parse(url)).also { startActivity(it) }
                         */
                        override fun onCreateWindow(
                            view: WebView?,
                            isDialog: Boolean,
                            isUserGesture: Boolean,
                            resultMsg: Message?
                        ): Boolean {
                            val newWebView = WebView(view?.context ?: return false)
                            val transport = resultMsg?.obj as? WebView.WebViewTransport
                            transport?.webView = newWebView
                            resultMsg?.sendToTarget()

                            newWebView.webViewClient = object : WebViewClient() {
                                override fun shouldOverrideUrlLoading(
                                    view: WebView?,
                                    request: WebResourceRequest?
                                ): Boolean {
                                    // 새 창의 URL을 메인 WebView에서 로드
                                    request?.url?.toString()?.let { url ->
                                        this@apply.loadUrl(url)
                                    }
                                    return true
                                }
                            }
                            return true
                        }
                    }

                    setDownloadListener { url, userAgent, contentDisposition, mimeType, _ ->
                        viewModel.downloadFile(url, userAgent, contentDisposition, mimeType)
                    }

                    // WebView 인스턴스를 Composable 레벨에서 참조 (ViewModel에서 분리)
                    webViewInstance = this
                    loadUrl(url)
                }
            },
            modifier = Modifier.fillMaxSize()
        )

        if (uiState.isLoading && uiState.progress < 100) {
            LinearProgressIndicator(
                progress = { uiState.progress / 100f },
                modifier = Modifier
                    .fillMaxWidth()
                    .align(Alignment.TopCenter)
            )
        }
    }
}
