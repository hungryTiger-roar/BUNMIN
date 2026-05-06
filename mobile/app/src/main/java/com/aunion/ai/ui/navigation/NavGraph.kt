package com.aunion.ai.ui.navigation

import androidx.compose.runtime.Composable
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import com.aunion.ai.ui.screens.url.UrlInputScreen
import com.aunion.ai.ui.screens.webview.WebViewScreen
import java.net.URLDecoder
import java.net.URLEncoder

sealed class Screen(val route: String) {
    data object UrlInput : Screen("url_input")
    data object WebView : Screen("webview/{url}") {
        fun createRoute(url: String): String {
            val encodedUrl = URLEncoder.encode(url, "UTF-8")
            return "webview/$encodedUrl"
        }
    }
}

@Composable
fun NavGraph(
    navController: NavHostController,
    startDestination: String = Screen.UrlInput.route
) {
    NavHost(
        navController = navController,
        startDestination = startDestination
    ) {
        composable(route = Screen.UrlInput.route) {
            UrlInputScreen(
                onNavigateToWebView = { url ->
                    navController.navigate(Screen.WebView.createRoute(url)) {
                        popUpTo(Screen.UrlInput.route) { inclusive = false }
                    }
                }
            )
        }

        composable(
            route = Screen.WebView.route,
            arguments = listOf(
                navArgument("url") { type = NavType.StringType }
            )
        ) { backStackEntry ->
            val encodedUrl = backStackEntry.arguments?.getString("url") ?: ""
            val url = URLDecoder.decode(encodedUrl, "UTF-8")
            WebViewScreen(url = url)
        }
    }
}
