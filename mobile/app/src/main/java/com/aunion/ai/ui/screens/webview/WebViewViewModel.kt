package com.aunion.ai.ui.screens.webview

import android.webkit.WebView
import androidx.lifecycle.ViewModel
import com.aunion.ai.core.app.Constants
import com.aunion.ai.data.download.DownloadRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import javax.inject.Inject

data class WebViewUiState(
    val url: String = Constants.STUDENT_START_URL,
    val isLoading: Boolean = true,
    val progress: Int = 0,
    val canGoBack: Boolean = false
)

@HiltViewModel
class WebViewViewModel @Inject constructor(
    private val downloadRepository: DownloadRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(WebViewUiState())
    val uiState: StateFlow<WebViewUiState> = _uiState.asStateFlow()

    private var webView: WebView? = null

    fun setWebView(webView: WebView) {
        this.webView = webView
    }

    fun updateLoadingState(isLoading: Boolean) {
        _uiState.value = _uiState.value.copy(isLoading = isLoading)
    }

    fun updateProgress(progress: Int) {
        _uiState.value = _uiState.value.copy(progress = progress)
    }

    fun updateCanGoBack(canGoBack: Boolean) {
        _uiState.value = _uiState.value.copy(canGoBack = canGoBack)
    }

    fun goBack(): Boolean {
        return if (_uiState.value.canGoBack && webView?.canGoBack() == true) {
            webView?.goBack()
            true
        } else {
            false
        }
    }

    fun downloadFile(
        url: String,
        userAgent: String?,
        contentDisposition: String?,
        mimeType: String?
    ) {
        downloadRepository.downloadFile(url, userAgent, contentDisposition, mimeType)
    }

    override fun onCleared() {
        super.onCleared()
        webView = null
    }
}
