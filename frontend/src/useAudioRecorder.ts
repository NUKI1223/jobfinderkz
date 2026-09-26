import {useEffect,useRef,useState} from 'react'
import {api,fileBody} from './api'
import {Action} from './shared'

/** A recording captures its destination before microphone permission resolves. */
export function useAudioRecorder(interviewId:string|undefined,index:number,act:Action) {
  const [recording,setRecording]=useState(false),[seconds,setSeconds]=useState(0),[error,setError]=useState('')
  const recorder=useRef<MediaRecorder|null>(null),stream=useRef<MediaStream|null>(null)
  const timer=useRef<ReturnType<typeof setInterval>|null>(null),mounted=useRef(true)
  const target=useRef({interviewId,index})
  target.current={interviewId,index}
  const stop=()=>{
    if(recorder.current?.state==='recording')recorder.current.stop()
    if(timer.current)clearInterval(timer.current)
    setRecording(false)
    stream.current?.getTracks().forEach(track=>track.stop())
  }
  useEffect(()=>()=>{
    mounted.current=false
    if(recorder.current?.state==='recording')recorder.current.stop()
    stream.current?.getTracks().forEach(track=>track.stop())
    if(timer.current)clearInterval(timer.current)
  },[])
  const start=async()=>{
    setError('')
    const destination={interviewId,index}
    try {
      const media=await navigator.mediaDevices.getUserMedia({audio:true})
      if(!mounted.current||target.current.interviewId!==destination.interviewId||target.current.index!==destination.index){
        media.getTracks().forEach(track=>track.stop());return
      }
      stream.current=media
      const mime=['audio/webm;codecs=opus','audio/webm','audio/mp4'].find(m=>MediaRecorder.isTypeSupported(m))
      const rec=new MediaRecorder(media,mime?{mimeType:mime}:undefined)
      recorder.current=rec
      const chunks:BlobPart[]=[]
      rec.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)}
      rec.onstop=()=>{
        if(!mounted.current)return
        const file=new File(chunks,'answer.'+(rec.mimeType.includes('mp4')?'mp4':'webm'),{type:rec.mimeType})
        void act(()=>api(`/interviews/${destination.interviewId}/audio?index=${destination.index}`,'POST',fileBody(file)))
      }
      rec.start();setRecording(true);setSeconds(0)
      let elapsed=0
      timer.current=setInterval(()=>{setSeconds(++elapsed);if(elapsed>=180)stop()},1000)
    }catch{
      stream.current?.getTracks().forEach(track=>track.stop())
      setError('Микрофон недоступен. Разрешите доступ в браузере или введите ответ текстом.')
    }
  }
  return {recording,seconds,error,setError,start,stop}
}
