import { Extension } from '@tiptap/core'

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    fontFamily: {
      setFontFamily: (fontFamily: string) => ReturnType
      unsetFontFamily: () => ReturnType
    }
  }
}

export const FontFamily = Extension.create({
  name: 'fontFamily',

  addGlobalAttributes() {
    return [
      {
        types: ['textStyle'],
        attributes: {
          fontFamily: {
            default: null,
            parseHTML: element => element.style.fontFamily?.replace(/['"]/g, '') || null,
            renderHTML: attributes => {
              if (!attributes.fontFamily) return {}
              const name = String(attributes.fontFamily)
              const quoted = name.includes(' ') ? `"${name}"` : name
              return { style: `font-family: ${quoted}` }
            },
          },
        },
      },
    ]
  },

  addCommands() {
    return {
      setFontFamily:
        (fontFamily: string) =>
        ({ editor, chain }) => {
          const attrs = { ...editor.getAttributes('textStyle'), fontFamily }
          return chain().setMark('textStyle', attrs).run()
        },
      unsetFontFamily:
        () =>
        ({ chain }) => {
          const c = chain().setMark('textStyle', { fontFamily: null }) as unknown as {
            removeEmptyTextStyle?: () => any
            run: () => boolean
          }
          return (c.removeEmptyTextStyle ? c.removeEmptyTextStyle().run() : c.run())
        },
    }
  },
})

