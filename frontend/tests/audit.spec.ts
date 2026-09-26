import {test,expect,Page} from '@playwright/test'

async function interviewFixture(page:Page) {
  await page.goto('/')
  await page.getByRole('button',{name:'Нет аккаунта? Зарегистрироваться'}).click()
  await page.getByLabel('Email',{exact:true}).fill(`audit-${Date.now()}@example.com`)
  await page.getByLabel('Пароль',{exact:true}).fill('audit-password-123')
  await page.getByRole('button',{name:'Создать аккаунт'}).click()
  await expect(page.getByRole('heading',{name:'Обзор',exact:true})).toBeVisible()
  const auth=await (await page.request.get('/api/v1/auth/me')).json()
  const headers={'X-CSRF-Token':auth.csrf}
  const sync=await (await page.request.post('/api/v1/vacancies/hh/sync',{headers,data:{text:'Python',direction:'python',level:'junior'}})).json()
  await expect.poll(async()=> (await (await page.request.get('/api/v1/jobs/'+sync.job_id)).json()).status).toBe('completed')
  const [vacancy]=await (await page.request.get('/api/v1/records/vacancy')).json()
  const ids:string[]=[]
  for(let i=0;i<2;i++) {
    const row=await (await page.request.post('/api/v1/interviews',{headers,data:{vacancy_id:vacancy.id,direction:'python',level:'junior',language:'ru'}})).json()
    ids.push(row.id)
  }
  await page.reload()
  await page.getByRole('button',{name:'Интервью',exact:true}).click()
  return ids
}

test('audio stays with its original interview after switch, lost response and reload',async({page})=>{
  await page.context().grantPermissions(['microphone'])
  const ids=await interviewFixture(page)
  let lost=false
  await page.route('**/api/v1/interviews/*/audio?index=0',async route=>{
    if(lost){await route.continue();return}
    lost=true
    await route.fetch()
    await route.abort('connectionfailed')
  })
  // Newest session is selected; switch to older while stopping the recorder.
  await page.getByRole('button',{name:'Записать ответ'}).click()
  await expect(page.getByRole('button',{name:/Остановить · [2-9] с/})).toBeVisible()
  await page.locator('aside.panel .list-item').last().click()
  await expect.poll(async()=>{
    const row=await (await page.request.get('/api/v1/record/'+ids[1])).json()
    return row.data.turns[0].transcript||''
  }).toContain('Транзакция')
  await expect(page.getByLabel('Ваш ответ',{exact:true})).toHaveValue('')
  const wrong=await (await page.request.get('/api/v1/record/'+ids[0])).json()
  expect(wrong.data.turns[0].transcript).toBeUndefined()
  await page.reload()
  await page.getByRole('button',{name:'Интервью',exact:true}).click()
  await expect(page.getByLabel('Ваш ответ',{exact:true})).toHaveValue(/Транзакция/)
  await expect(page.getByLabel('Я проверил текст ответа')).not.toBeChecked()
})

test('statistics discard a stale response when switching language',async({page})=>{
  await interviewFixture(page)
  await page.route('**/api/v1/stats?*',async route=>{
    const language=new URL(route.request().url()).searchParams.get('language')
    if(language==='ru')await new Promise(resolve=>setTimeout(resolve,800))
    await route.fulfill({json:{timeline:[{id:language,date:'2026-09-25',score:language==='en'?4:1,answers:5}],topics:[],errors:[]}})
  })
  await page.getByRole('button',{name:'Мой прогресс',exact:true}).click()
  await page.getByLabel('Язык',{exact:true}).selectOption('en')
  await expect(page.getByText('4 / 4',{exact:true})).toBeVisible()
  await page.waitForTimeout(1000)
  await expect(page.getByText('4 / 4',{exact:true})).toBeVisible()
})
