import type { ReactNode } from 'react'
import type { Flag } from '../model.ts'

const TONES = {
  slate: 'bg-slate-100 text-slate-700 ring-slate-200',
  teal: 'bg-teal-50 text-teal-800 ring-teal-200',
  rose: 'bg-rose-50 text-rose-700 ring-rose-200',
  amber: 'bg-amber-50 text-amber-800 ring-amber-200',
  blue: 'bg-blue-50 text-blue-700 ring-blue-200',
  violet: 'bg-violet-50 text-violet-700 ring-violet-200',
}
export type Tone = keyof typeof TONES

export function Badge({ tone = 'slate', title, children }: { tone?: Tone; title?: string; children: ReactNode }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-md px-1.5 py-0.5 text-[11px] font-medium ring-1 ring-inset ${TONES[tone]}`}
    >
      {children}
    </span>
  )
}

export function Card({
  title,
  subtitle,
  action,
  flush = false,
  className = '',
  children,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  action?: ReactNode
  flush?: boolean
  className?: string
  children: ReactNode
}) {
  return (
    <section className={`rounded-xl border border-slate-200 bg-white shadow-sm ${className}`}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 border-b border-slate-100 px-4 py-3">
          <div className="min-w-0">
            <h2 className="text-sm font-semibold text-slate-900">{title}</h2>
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={flush ? '' : 'px-4 py-3'}>{children}</div>
    </section>
  )
}

export function FlagMark({ flag }: { flag?: Flag }) {
  if (!flag) return null
  return (
    <span
      title={flag === 'H' ? 'Above reference range' : 'Below reference range'}
      className={`ml-1 inline-block rounded px-1 align-[1px] text-[10px] font-bold leading-4 ${
        flag === 'H' ? 'bg-rose-100 text-rose-700' : 'bg-blue-100 text-blue-700'
      }`}
    >
      {flag}
    </span>
  )
}

export function valueTone(flag?: Flag): string {
  return flag === 'H' ? 'text-rose-700' : flag === 'L' ? 'text-blue-700' : 'text-slate-900'
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="py-1 text-sm text-slate-500">{children}</p>
}

export function Loading({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 py-16 text-sm text-slate-500">
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-teal-700" />
      {label}
    </div>
  )
}

export function ErrorPanel({ error }: { error: Error }) {
  return (
    <div className="my-8 rounded-xl border border-rose-200 bg-rose-50 px-5 py-4 text-sm text-rose-900">
      <p className="font-semibold">Could not load data from the FHIR server.</p>
      <p className="mt-1 text-rose-800">{error.message}</p>
      <p className="mt-3 text-rose-800">
        Start the server with <code className="rounded bg-white/70 px-1">docker compose up -d</code> and load the
        synthetic records with <code className="rounded bg-white/70 px-1">python synthetic/load.py</code>, then reload
        this page.
      </p>
    </div>
  )
}

const isHeading = (line: string) => line.length > 2 && line.length < 70 && /[A-Z]/.test(line) && line === line.toUpperCase()

/** Plain-text clinical documents, with their upper-case section headings set as headings. */
export function DocumentText({ text }: { text: string }) {
  return (
    <div className="text-[13.5px] leading-relaxed text-slate-800">
      {text.split('\n').map((line, index) =>
        line.trim() === '' ? null : isHeading(line) ? (
          <h3 key={index} className="pb-0.5 pt-4 text-[11px] font-semibold tracking-wider text-slate-500 first:pt-0">
            {line}
          </h3>
        ) : (
          <p key={index} className="whitespace-pre-wrap">
            {line}
          </p>
        ),
      )}
    </div>
  )
}
