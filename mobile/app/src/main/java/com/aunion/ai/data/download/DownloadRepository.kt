package com.aunion.ai.data.download

import android.app.DownloadManager
import android.content.Context
import android.net.Uri
import android.os.Environment
import android.webkit.CookieManager
import android.webkit.MimeTypeMap
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class DownloadRepository @Inject constructor(
    @ApplicationContext private val context: Context,
    private val downloadManager: DownloadManager
) {
    /**
     * URL에서 파일 다운로드
     * @param url 다운로드 URL
     * @param userAgent User-Agent 헤더
     * @param contentDisposition Content-Disposition 헤더
     * @param mimeType MIME 타입
     * @return 다운로드 ID
     */
    fun downloadFile(
        url: String,
        userAgent: String?,
        contentDisposition: String?,
        mimeType: String?
    ): Long {
        val fileName = extractFileName(url, contentDisposition, mimeType)

        val request = DownloadManager.Request(Uri.parse(url)).apply {
            setTitle(fileName)
            setDescription("Aunion AI 다운로드 중...")
            setMimeType(mimeType)
            setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
            setDestinationInExternalPublicDir(Environment.DIRECTORY_DOWNLOADS, fileName)

            // User-Agent 헤더 추가
            userAgent?.let { addRequestHeader("User-Agent", it) }

            // 쿠키 헤더 추가 (로그인 세션 유지)
            val cookies = CookieManager.getInstance().getCookie(url)
            cookies?.let { addRequestHeader("Cookie", it) }
        }

        return downloadManager.enqueue(request)
    }

    private fun extractFileName(
        url: String,
        contentDisposition: String?,
        mimeType: String?
    ): String {
        // Content-Disposition에서 파일명 추출 시도
        contentDisposition?.let { disposition ->
            val fileNameMatch = Regex("filename=\"?([^\"]+)\"?").find(disposition)
            fileNameMatch?.groupValues?.get(1)?.let { return it }
        }

        // URL에서 파일명 추출
        val urlFileName = url.substringAfterLast("/").substringBefore("?")
        if (urlFileName.isNotEmpty() && urlFileName.contains(".")) {
            return urlFileName
        }

        // 기본 파일명 + 확장자 (MIME 타입에서 추출, 없으면 bin)
        val extension = MimeTypeMap.getSingleton().getExtensionFromMimeType(mimeType) ?: "bin"
        return "aunion_download_${System.currentTimeMillis()}.$extension"
    }
}
