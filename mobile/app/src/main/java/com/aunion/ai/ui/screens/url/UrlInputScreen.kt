package com.aunion.ai.ui.screens.url

import android.content.Context
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Clear
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private const val PREFS_NAME = "aunion_prefs"
private const val KEY_LAST_URL = "last_url"

/**
 * URL 정규화 - http/https 프로토콜 자동 추가
 */
private fun normalizeUrl(input: String): String {
    val trimmed = input.trim()
    return when {
        trimmed.isEmpty() -> trimmed
        trimmed.startsWith("http://") || trimmed.startsWith("https://") -> trimmed
        trimmed.startsWith("192.") || trimmed.startsWith("10.") || trimmed.startsWith("172.") -> "http://$trimmed"
        else -> "http://$trimmed"
    }
}

/**
 * URL 유효성 검사
 */
private fun isValidUrl(url: String): Boolean {
    if (url.isBlank()) return false
    val normalized = normalizeUrl(url)
    return normalized.startsWith("http://") || normalized.startsWith("https://")
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun UrlInputScreen(
    onNavigateToWebView: (String) -> Unit
) {
    val context = LocalContext.current
    val prefs = context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    var url by remember {
        mutableStateOf(prefs.getString(KEY_LAST_URL, "") ?: "")
    }
    var isError by remember { mutableStateOf(false) }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(MaterialTheme.colorScheme.background)
            .padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text(
            text = "Aunion AI",
            fontSize = 32.sp,
            fontWeight = FontWeight.Bold,
            color = MaterialTheme.colorScheme.primary
        )

        Spacer(modifier = Modifier.height(8.dp))

        Text(
            text = "수강자 앱",
            fontSize = 16.sp,
            color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.7f)
        )

        Spacer(modifier = Modifier.height(48.dp))

        OutlinedTextField(
            value = url,
            onValueChange = {
                url = it
                isError = false
            },
            label = { Text("강의 URL 입력") },
            placeholder = { Text("http://192.168.0.1:3000/#/student/start") },
            singleLine = true,
            isError = isError,
            supportingText = {
                if (isError) {
                    Text("올바른 URL을 입력해주세요")
                }
            },
            trailingIcon = {
                if (url.isNotEmpty()) {
                    IconButton(onClick = { url = "" }) {
                        Icon(
                            imageVector = Icons.Filled.Clear,
                            contentDescription = "URL 삭제",
                            tint = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            },
            keyboardOptions = KeyboardOptions(
                keyboardType = KeyboardType.Uri,
                imeAction = ImeAction.Go
            ),
            keyboardActions = KeyboardActions(
                onGo = {
                    if (isValidUrl(url)) {
                        val normalizedUrl = normalizeUrl(url)
                        prefs.edit().putString(KEY_LAST_URL, normalizedUrl).apply()
                        onNavigateToWebView(normalizedUrl)
                    } else {
                        isError = true
                    }
                }
            ),
            modifier = Modifier.fillMaxWidth()
        )

        Spacer(modifier = Modifier.height(24.dp))

        Button(
            onClick = {
                if (isValidUrl(url)) {
                    val normalizedUrl = normalizeUrl(url)
                    prefs.edit().putString(KEY_LAST_URL, normalizedUrl).apply()
                    onNavigateToWebView(normalizedUrl)
                } else {
                    isError = true
                }
            },
            modifier = Modifier
                .fillMaxWidth()
                .height(56.dp),
            enabled = url.isNotBlank()
        ) {
            Text(
                text = "강의 참여",
                fontSize = 18.sp,
                fontWeight = FontWeight.Medium
            )
        }

        Spacer(modifier = Modifier.height(16.dp))

        Text(
            text = "강의자가 공유한 URL을 입력하세요",
            fontSize = 14.sp,
            color = MaterialTheme.colorScheme.onBackground.copy(alpha = 0.5f)
        )
    }
}
