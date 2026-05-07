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
              return { style: `font-family: ${attributes.fontFamily}` }
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
        ({ chain }) => {
          return chain().setMark('textStyle', { fontFamily }).run()
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

