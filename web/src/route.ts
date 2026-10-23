import { useEffect, useState } from 'react'

export const TABS = ['overview', 'labs', 'visits', 'reports'] as const
export type Tab = (typeof TABS)[number]

export type Route = { page: 'worklist' } | { page: 'patient'; id: string; tab: Tab; item?: string }

function parse(hash: string): Route {
  const [page, id, tab, item] = hash.replace(/^#\/?/, '').split('/').map(decodeURIComponent)
  if (page === 'patients' && id) {
    const known = (TABS as readonly string[]).includes(tab) ? (tab as Tab) : 'overview'
    return { page: 'patient', id, tab: known, item: item || undefined }
  }
  return { page: 'worklist' }
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash))
  useEffect(() => {
    const update = () => setRoute(parse(window.location.hash))
    window.addEventListener('hashchange', update)
    return () => window.removeEventListener('hashchange', update)
  }, [])
  return route
}

export function patientHref(id: string, tab: Tab = 'overview', item?: string): string {
  const parts = ['#', 'patients', encodeURIComponent(id)]
  if (tab !== 'overview' || item) parts.push(tab)
  if (item) parts.push(encodeURIComponent(item))
  return parts.join('/')
}

/** Changes the selection inside a tab without adding a history entry. */
export function select(id: string, tab: Tab, item: string): void {
  window.location.replace(patientHref(id, tab, item))
}
