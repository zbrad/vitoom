import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { i18n } from '../i18n'

let lastRoute: RouteLocationNormalizedLoaded | null = null

export function getRouteTitleKey(route: RouteLocationNormalizedLoaded): string | undefined {
  for (let i = route.matched.length - 1; i >= 0; i--) {
    const key = route.matched[i]?.meta?.titleKey
    if (typeof key === 'string' && key.trim()) return key
  }
  return undefined
}

export function formatPageTitle(titleKey?: string): string {
  const appName = String(i18n.global.t('common.appName') || 'Vitoom').trim() || 'Vitoom'
  const pageKey = String(titleKey || '').trim()
  if (!pageKey) return appName

  const page = String(i18n.global.t(pageKey) || '').trim()
  if (!page || page === pageKey) return appName

  return String(
    i18n.global.t('common.pageTitleTemplate', {
      page,
      app: appName,
    }) || `${page} - ${appName}`
  ).trim()
}

export function updatePageTitle(route?: RouteLocationNormalizedLoaded) {
  if (route) lastRoute = route
  const target = route || lastRoute
  document.title = formatPageTitle(target ? getRouteTitleKey(target) : undefined)
}
