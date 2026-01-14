import { Extension } from '@tiptap/core'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'

export interface RiskHighlightOptions {
  risks: Array<{
    id: string
    from: number
    to: number
    level: 'high' | 'medium' | 'low'
    description: string
  }>
}

export const RiskHighlight = Extension.create<RiskHighlightOptions>({
  name: 'riskHighlight',

  addOptions() {
    return {
      risks: [],
    }
  },

  addProseMirrorPlugins() {
    const extension = this

    return [
      new Plugin({
        key: new PluginKey('riskHighlight'),
        state: {
          init() {
            return DecorationSet.empty
          },
          apply(tr, set) {
            const decorations: Decoration[] = []
            const risks = extension.options.risks || []

            risks.forEach((risk) => {
              const colorMap = {
                high: 'rgba(239, 68, 68, 0.3)',
                medium: 'rgba(251, 191, 36, 0.3)',
                low: 'rgba(59, 130, 246, 0.3)',
              }
              const borderColorMap = {
                high: 'rgba(239, 68, 68, 0.6)',
                medium: 'rgba(251, 191, 36, 0.6)',
                low: 'rgba(59, 130, 246, 0.6)',
              }

              const decoration = Decoration.inline(
                risk.from,
                risk.to,
                {
                  class: `risk-highlight risk-${risk.level}`,
                  style: `background-color: ${colorMap[risk.level]}; border-bottom: 2px solid ${borderColorMap[risk.level]}; padding: 0 2px; border-radius: 2px; cursor: help;`,
                  'data-risk-id': risk.id,
                  'data-risk-description': risk.description,
                  title: `Риск (${risk.level}): ${risk.description}`,
                }
              )
              decorations.push(decoration)
            })

            return DecorationSet.create(tr.doc, decorations)
          },
        },
        props: {
          decorations(state) {
            return this.getState(state)
          },
        },
      }),
    ]
  },

  addCommands() {
    return {
      addRisk: (from: number, to: number, level: 'high' | 'medium' | 'low', description: string, id?: string) => ({ tr, dispatch }) => {
        if (dispatch) {
          if (!this.options.risks) {
            this.options.risks = []
          }
          const riskId = id || `risk-${Date.now()}`
          this.options.risks.push({
            id: riskId,
            from,
            to,
            level,
            description,
          })
          dispatch(tr)
        }
        return true
      },
      removeRisk: (id: string) => ({ tr, dispatch }) => {
        if (dispatch) {
          if (this.options.risks) {
            this.options.risks = this.options.risks.filter((r) => r.id !== id)
            dispatch(tr)
          }
        }
        return true
      },
      clearRisks: () => ({ tr, dispatch }) => {
        if (dispatch) {
          this.options.risks = []
          dispatch(tr)
        }
        return true
      },
      setRisks: (risks: RiskHighlightOptions['risks']) => ({ tr, dispatch }) => {
        if (dispatch) {
          this.options.risks = risks
          dispatch(tr)
        }
        return true
      },
    }
  },
})

