// Clinic-local time, so dates read the same as in the notes whatever the viewer's time zone.
const TIME_ZONE = 'Europe/Istanbul'
const DAY_MS = 86_400_000

// Same month abbreviations as the notes and reports, so on-screen dates match the source text.
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

const formats = {
  weekday: new Intl.DateTimeFormat('en-GB', { weekday: 'long', day: 'numeric', month: 'long', timeZone: TIME_ZONE }),
  time: new Intl.DateTimeFormat('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: TIME_ZONE }),
  iso: new Intl.DateTimeFormat('en-CA', { year: 'numeric', month: '2-digit', day: '2-digit', timeZone: TIME_ZONE }),
}

type Moment = string | number

export const toTime = (value: string | undefined): number => (value ? Date.parse(value) : Number.NaN)

/** Calendar day (YYYY-MM-DD) in clinic time. */
export const isoDay = (value: Moment): string => formats.iso.format(new Date(value))

function parts(value: Moment): { year: number; month: string; day: number } {
  const [year, month, day] = isoDay(value).split('-').map(Number)
  return { year, month: MONTHS[month - 1], day }
}

export function formatDate(value: Moment | undefined): string {
  if (value === undefined) return '—'
  const { year, month, day } = parts(value)
  return `${day} ${month} ${year}`
}

export function formatDayMonth(value: Moment): string {
  const { month, day } = parts(value)
  return `${day} ${month}`
}

export function formatMonthYear(value: Moment): string {
  const { year, month } = parts(value)
  return `${month} ’${String(year).slice(2)}`
}

export const formatWeekday = (value: Moment): string => formats.weekday.format(new Date(value))
export const formatTime = (value: Moment): string => formats.time.format(new Date(value))
export const todayIso = (): string => isoDay(Date.now())

export function daysBetween(fromDay: string, toDay: string): number {
  return Math.round((Date.parse(toDay) - Date.parse(fromDay)) / DAY_MS)
}

export function ageOn(birthDate: string | undefined, day: string): number | undefined {
  if (!birthDate) return undefined
  const [year, month, date] = birthDate.split('-').map(Number)
  const [toYear, toMonth, toDate] = day.split('-').map(Number)
  return toYear - year - (toMonth < month || (toMonth === month && toDate < date) ? 1 : 0)
}

export function relativeDay(day: string, today = todayIso()): string {
  const days = daysBetween(today, day)
  if (days === 0) return 'today'
  if (days === 1) return 'tomorrow'
  if (days === -1) return 'yesterday'
  return days > 0 ? `in ${days} days` : `${-days} days ago`
}

export function formatNumber(value: number, decimals: number): string {
  return value.toFixed(decimals)
}

export function signed(value: number, decimals: number): string {
  const magnitude = Math.abs(value).toFixed(decimals)
  if (Number(magnitude) === 0) return magnitude
  return `${value < 0 ? '−' : '+'}${magnitude}`
}

export function sexLabel(gender: string | undefined): string {
  return gender === 'male' ? 'Male' : gender === 'female' ? 'Female' : 'Unknown'
}
