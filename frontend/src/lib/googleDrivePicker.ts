/**
 * Google Picker + OAuth token (GIS). Loads scripts once; no React wrapper dependency.
 */

const GAPI_SCRIPT = 'https://apis.google.com/js/api.js'
const GIS_SCRIPT = 'https://accounts.google.com/gsi/client'
const DRIVE_READONLY_SCOPE = 'https://www.googleapis.com/auth/drive.readonly'

/** MIME types we can ingest after export/download (matches backend ALLOWED_EXTENSIONS). */
const PICKER_MIME_TYPES = [
  'application/pdf',
  'application/vnd.google-apps.document',
  'application/vnd.google-apps.spreadsheet',
  'application/vnd.google-apps.presentation',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  'text/plain',
  'text/csv',
  'image/png',
  'image/jpeg',
  'image/webp',
  'image/gif',
  'image/bmp',
  'image/tiff',
].join(',')

export type PickedDriveDoc = {
  id: string
  name: string
  mimeType: string
}

export type GoogleDrivePickResult = {
  accessToken: string
  docs: PickedDriveDoc[]
}

type PickerDoc = {
  id?: string
  name?: string
  mimeType?: string
}

type DocsViewInstance = {
  setIncludeFolders: (include: boolean) => DocsViewInstance
  setOwnedByMe: (owned: boolean) => DocsViewInstance
  setEnableTeamDrives: (enable: boolean) => DocsViewInstance
  setSelectFolderEnabled: (enable: boolean) => DocsViewInstance
  setMimeTypes: (mimeTypes: string) => DocsViewInstance
  setLabel?: (label: string) => DocsViewInstance
}

type PickerBuilderInstance = {
  addView: (view: string | DocsViewInstance) => PickerBuilderInstance
  setOAuthToken: (token: string) => PickerBuilderInstance
  setDeveloperKey: (key: string) => PickerBuilderInstance
  setCallback: (cb: (data: PickerResponseData) => void) => PickerBuilderInstance
  enableFeature: (feature: string) => PickerBuilderInstance
  setTitle: (title: string) => PickerBuilderInstance
  setLocale: (locale: string) => PickerBuilderInstance
  build: () => { setVisible: (v: boolean) => void }
}

type PickerResponseData = {
  action: string
  docs?: PickerDoc[]
}

declare global {
  interface Window {
    gapi?: {
      load: (name: string, opts: { callback: () => void }) => void
    }
    google?: {
      accounts: {
        oauth2: {
          initTokenClient: (config: {
            client_id: string
            scope: string
            callback: (resp: { access_token?: string; error?: string }) => void
          }) => { requestAccessToken: (opts?: { prompt?: string }) => void }
        }
      }
      picker?: {
        Action: { PICKED: string; CANCEL: string }
        Response?: { ACTION: string; DOCUMENTS: string }
        ViewId: { DOCS: string; FOLDERS: string }
        DocsView: new (viewId?: string) => DocsViewInstance
        PickerBuilder: new () => PickerBuilderInstance
        Feature: {
          MULTISELECT_ENABLED: string
          SUPPORT_DRIVES: string
          NAV_HIDDEN: string
        }
      }
    }
  }
}

let scriptsPromise: Promise<void> | null = null

function loadScript(src: string, id: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (document.getElementById(id)) {
      resolve()
      return
    }
    const el = document.createElement('script')
    el.id = id
    el.src = src
    el.async = true
    el.defer = true
    el.onload = () => resolve()
    el.onerror = () => reject(new Error(`Failed to load script: ${src}`))
    document.head.appendChild(el)
  })
}

function loadPickerApi(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (!window.gapi?.load) {
      reject(new Error('Google API (gapi) not available'))
      return
    }
    window.gapi.load('picker', {
      callback: () => resolve(),
    })
  })
}

function buildPickerViews(pickerNs: NonNullable<Window['google']>['picker']): DocsViewInstance[] {
  const DocsView = pickerNs!.DocsView
  const docsId = pickerNs!.ViewId.DOCS

  const label = (view: DocsViewInstance, text: string) =>
    typeof view.setLabel === 'function' ? view.setLabel(text) : view

  const myDrive = label(
    new DocsView(docsId)
      .setIncludeFolders(true)
      .setSelectFolderEnabled(false)
      .setOwnedByMe(true)
      .setMimeTypes(PICKER_MIME_TYPES),
    'Мой диск',
  )

  const sharedWithMe = label(
    new DocsView(docsId)
      .setIncludeFolders(true)
      .setSelectFolderEnabled(false)
      .setOwnedByMe(false)
      .setMimeTypes(PICKER_MIME_TYPES),
    'Доступные мне',
  )

  const teamDrives = label(
    new DocsView(docsId)
      .setIncludeFolders(true)
      .setSelectFolderEnabled(false)
      .setEnableTeamDrives(true)
      .setMimeTypes(PICKER_MIME_TYPES),
    'Диски команды',
  )

  return [myDrive, sharedWithMe, teamDrives]
}

function getPickerAction(
  data: PickerResponseData,
  pickerNs: NonNullable<Window['google']>['picker'],
): string | undefined {
  if (data.action) return data.action
  const key = pickerNs?.Response?.ACTION
  if (key && typeof data === 'object') {
    return (data as Record<string, unknown>)[key] as string | undefined
  }
  return undefined
}

function getPickerDocuments(
  data: PickerResponseData,
  pickerNs: NonNullable<Window['google']>['picker'],
): PickerDoc[] | undefined {
  if (data.docs?.length) return data.docs
  const key = pickerNs?.Response?.DOCUMENTS
  if (key && typeof data === 'object') {
    const docs = (data as Record<string, unknown>)[key]
    if (Array.isArray(docs)) return docs as PickerDoc[]
  }
  return data.docs
}

export function loadGooglePickerScripts(): Promise<void> {
  if (!scriptsPromise) {
    scriptsPromise = (async () => {
      await loadScript(GIS_SCRIPT, 'google-gis')
      await loadScript(GAPI_SCRIPT, 'google-gapi')
      await loadPickerApi()
    })()
  }
  return scriptsPromise
}

export function isGoogleDriveImportConfigured(): boolean {
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID?.trim()
  const apiKey = import.meta.env.VITE_GOOGLE_API_KEY?.trim()
  return Boolean(clientId && apiKey)
}

function requestAccessToken(clientId: string): Promise<string> {
  return new Promise((resolve, reject) => {
    if (!window.google?.accounts?.oauth2) {
      reject(new Error('Google Identity Services не загрузился'))
      return
    }
    const client = window.google.accounts.oauth2.initTokenClient({
      client_id: clientId,
      scope: DRIVE_READONLY_SCOPE,
      callback: (resp) => {
        if (resp.error) {
          reject(new Error(resp.error))
          return
        }
        if (!resp.access_token) {
          reject(new Error('Не получен access token от Google'))
          return
        }
        resolve(resp.access_token)
      },
    })
    client.requestAccessToken({ prompt: '' })
  })
}

export async function openGoogleDrivePicker(): Promise<GoogleDrivePickResult> {
  const clientId = import.meta.env.VITE_GOOGLE_CLIENT_ID?.trim()
  const developerKey = import.meta.env.VITE_GOOGLE_API_KEY?.trim()
  if (!clientId || !developerKey) {
    throw new Error(
      'Google Drive не настроен: задайте VITE_GOOGLE_CLIENT_ID и VITE_GOOGLE_API_KEY',
    )
  }

  await loadGooglePickerScripts()
  const accessToken = await requestAccessToken(clientId)

  const pickerNs = window.google?.picker
  if (!pickerNs?.DocsView) {
    throw new Error('Google Picker API недоступен')
  }

  const views = buildPickerViews(pickerNs)

  return new Promise((resolve, reject) => {
    let settled = false
    const finish = (fn: () => void) => {
      if (settled) return
      settled = true
      fn()
    }

    let builder = new pickerNs.PickerBuilder()
    for (const view of views) {
      builder = builder.addView(view)
    }
    const picker = builder
      .setOAuthToken(accessToken)
      .setDeveloperKey(developerKey)
      .enableFeature(pickerNs.Feature.MULTISELECT_ENABLED)
      .enableFeature(pickerNs.Feature.SUPPORT_DRIVES)
      .setLocale('ru')
      .setTitle('Google Drive — Мой диск / Доступные мне / Диски команды')
      .setCallback((data: PickerResponseData) => {
        const action = getPickerAction(data, pickerNs)
        if (!action) return

        if (action === pickerNs.Action.CANCEL) {
          finish(() => reject(new Error('Выбор отменён')))
          return
        }

        // Picker fires many intermediate callbacks (loaded, view change, etc.)
        if (action !== pickerNs.Action.PICKED) return

        const rawDocs = getPickerDocuments(data, pickerNs)
        if (!rawDocs?.length) {
          finish(() =>
            reject(
              new Error(
                'Файлы не выбраны: выберите документы (не папки) и нажмите «Выбрать»',
              ),
            ),
          )
          return
        }

        const docs: PickedDriveDoc[] = rawDocs
          .filter((d: PickerDoc) => d.id && d.name && d.mimeType)
          .map((d: PickerDoc) => ({
            id: d.id as string,
            name: d.name as string,
            mimeType: d.mimeType as string,
          }))
        if (!docs.length) {
          finish(() =>
            reject(
              new Error(
                'Не удалось прочитать выбранные файлы (нужны PDF, DOCX, Google Docs/Sheets и т.п.)',
              ),
            ),
          )
          return
        }
        finish(() => resolve({ accessToken, docs }))
      })
      .build()

    picker.setVisible(true)
  })
}
