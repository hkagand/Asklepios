import type { ReactNode } from 'react'
import type { Flag } from '../model.ts'

// Status chips: a tinted ground with a darker rule on the left edge, like a tab on a chart divider.
const TONES = {
  slate: 'bg-slate-100 text-slate-700 border-slate-400',
  teal: 'bg-teal-50 text-teal-800 border-teal-600',
  rose: 'bg-rose-50 text-rose-700 border-rose-500',
  amber: 'bg-amber-50 text-amber-800 border-amber-500',
  blue: 'bg-blue-50 text-blue-800 border-blue-500',
  violet: 'bg-violet-50 text-violet-800 border-violet-500',
}
export type Tone = keyof typeof TONES

export function Badge({ tone = 'slate', title, children }: { tone?: Tone; title?: string; children: ReactNode }) {
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 whitespace-nowrap rounded-sm border-l-[3px] py-px pl-1.5 pr-2 text-[11.5px] font-semibold leading-[18px] ${TONES[tone]}`}
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
    <section className={`rounded-lg border border-slate-200 bg-sheet ${className}`}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 border-b border-slate-200 px-4 pb-2.5 pt-3">
          <div className="min-w-0">
            <h2 className="text-[15px] font-bold leading-snug tracking-[-0.01em] text-slate-900">{title}</h2>
            {subtitle && <p className="mt-0.5 text-[12.5px] text-slate-500">{subtitle}</p>}
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
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-300 border-t-slate-900" />
      {label}
    </div>
  )
}

export function ErrorPanel({ error }: { error: Error }) {
  return (
    <div className="my-8 rounded-lg border-l-4 border-rose-500 bg-rose-50 px-5 py-4 text-sm text-rose-900">
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
    <div className="max-w-[72ch] text-[14px] leading-relaxed text-slate-800">
      {text.split('\n').map((line, index) =>
        line.trim() === '' ? null : isHeading(line) ? (
          <h3 key={index} className="pb-0.5 pt-4 text-[12px] font-bold text-slate-600 first:pt-0">
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
