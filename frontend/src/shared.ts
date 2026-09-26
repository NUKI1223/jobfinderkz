import {CVFacts, ProfileData} from './models'
export const emptyFacts:CVFacts = {summary:'', skills:[], experience:[], education:[], projects:[], languages:[]}
export const defaultProfile:ProfileData = {direction:'frontend',level:'junior',regions:['Казахстан'],work_format:'any',language:'ru'}
export type Action = (fn: () => Promise<unknown>, message?: string) => Promise<void>
