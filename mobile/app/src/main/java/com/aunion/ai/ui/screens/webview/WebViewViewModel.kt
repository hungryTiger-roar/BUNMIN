package com.aunion.ai.ui.screens.webview

import androidx.lifecycle.ViewModel
import com.aunion.ai.data.download.DownloadRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.flow.asStateFlow
import javax.inject.Inject

data class WebViewUiState(
    val isLoading: Boolean = true,
    val progress: Int = 0,
    val canGoBack: Boolean = false
)

/**
 * WebView 명령 이벤트
 * ViewModel이 View에 직접 의존하지 않고, 이벤트를 통해 명령을 전달
 */
sealed class WebViewCommand {
    data object GoBack : WebViewCommand()
}

@HiltViewModel
class WebViewViewModel @Inject constructor(
    private val downloadRepository: DownloadRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(WebViewUiState())
    val uiState: StateFlow<WebViewUiState> = _uiState.asStateFlow()

    // WebView 명령을 전달하기 위한 SharedFlow
    private val _commands = MutableSharedFlow<WebViewCommand>(extraBufferCapacity = 1)
    val commands: SharedFlow<WebViewCommand> = _commands.asSharedFlow()

    fun updateLoadingState(isLoading: Boolean) {
        _uiState.value = _uiState.value.copy(isLoading = isLoading)
    }

    fun updateProgress(progress: Int) {
        _uiState.value = _uiState.value.copy(progress = progress)
    }

    fun updateCanGoBack(canGoBack: Boolean) {
        _uiState.value = _uiState.value.copy(canGoBack = canGoBack)
    }

    /**
     * 뒤로가기 명령 발행
     * Composable에서 이 이벤트를 수신하여 WebView.goBack() 실행
     */
    fun goBack() {
        if (_uiState.value.canGoBack) {
            _commands.tryEmit(WebViewCommand.GoBack)
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
}
