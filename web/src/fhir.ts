export type Resource = fhir4.FhirResource

const BASE = '/fhir'

async function getJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  let response: Response
  try {
    response = await fetch(url, { headers: { Accept: 'application/fhir+json' }, signal })
  } catch (error) {
    if (signal?.aborted) throw error
    throw new Error('Could not reach the FHIR server.', { cause: error })
  }
  if (!response.ok) {
    throw new Error(`The FHIR server answered ${response.status} ${response.statusText} for ${url}`)
  }
  return (await response.json()) as T
}

export function read<T extends Resource>(type: T['resourceType'], id: string, signal?: AbortSignal): Promise<T> {
  return getJson<T>(`${BASE}/${type}/${encodeURIComponent(id)}`, signal)
}

/** Runs a search and follows `next` links until every page has been read. */
export async function search<T extends Resource>(
  type: T['resourceType'],
  params: Record<string, string>,
  signal?: AbortSignal,
): Promise<T[]> {
  const resources: T[] = []
  let url: string | undefined = `${BASE}/${type}?${new URLSearchParams({ _count: '200', ...params })}`
  while (url) {
    const bundle: fhir4.Bundle = await getJson<fhir4.Bundle>(url, signal)
    for (const entry of bundle.entry ?? []) {
      if (entry.resource?.resourceType === type) resources.push(entry.resource as T)
    }
    const next = bundle.link?.find((link) => link.relation === 'next')?.url
    url = next && throughProxy(next)
  }
  return resources
}

// The server writes absolute paging links to itself; the browser must stay on the dev proxy.
function throughProxy(link: string): string {
  const url = new URL(link, window.location.origin)
  return url.pathname + url.search
}

export function resourceUrl(resource: Resource): string {
  return `${BASE}/${resource.resourceType}/${resource.id}`
}

export function decodeBase64(data: string): string {
  const binary = atob(data)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index++) bytes[index] = binary.charCodeAt(index)
  return new TextDecoder().decode(bytes)
}

export function attachmentText(attachments: fhir4.Attachment[] | undefined): string | undefined {
  const data = attachments?.find((attachment) => attachment.data)?.data
  return data ? decodeBase64(data) : undefined
}

export function text(concept: fhir4.CodeableConcept | undefined): string {
  return concept?.text ?? concept?.coding?.[0]?.display ?? concept?.coding?.[0]?.code ?? ''
}

export function code(concept: fhir4.CodeableConcept | undefined): string | undefined {
  return concept?.coding?.[0]?.code
}

export function refId(reference: fhir4.Reference | undefined): string | undefined {
  return reference?.reference?.split('/')[1]
}

export function patientName(patient: fhir4.Patient): string {
  const name = patient.name?.[0]
  return name?.text ?? [name?.given?.join(' '), name?.family].filter(Boolean).join(' ')
}

export function medicalRecordNumber(patient: fhir4.Patient): string | undefined {
  return patient.identifier?.find((identifier) => identifier.type?.coding?.some((coding) => coding.code === 'MR'))?.value
}

export function isSynthetic(resource: Resource): boolean {
  return resource.meta?.security?.some((label) => label.code === 'HTEST') ?? false
}
