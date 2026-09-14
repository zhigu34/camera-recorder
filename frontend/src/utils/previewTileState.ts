export type PreviewTileState = 'idle' | 'connecting' | 'playing' | 'paused' | 'retrying' | 'error'

export type PreviewTilePrimaryAction = 'start' | 'pause' | 'resume' | 'retry'

export function tilePrimaryAction(state: PreviewTileState): PreviewTilePrimaryAction {
  if (state === 'playing' || state === 'connecting' || state === 'retrying') return 'pause'
  if (state === 'paused') return 'resume'
  if (state === 'error') return 'retry'
  return 'start'
}

export function tilePrimaryLabel(state: PreviewTileState) {
  const action = tilePrimaryAction(state)
  if (action === 'pause') return '暂停'
  if (action === 'resume') return '继续'
  if (action === 'retry') return '重试'
  return '开始'
}

export function shouldResumeAfterVisibility(startedByUser: boolean, wasActiveBeforeHide: boolean) {
  return startedByUser && wasActiveBeforeHide
}

export function isActiveTileState(state: PreviewTileState) {
  return state === 'connecting' || state === 'playing' || state === 'retrying'
}
