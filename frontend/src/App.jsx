import { useEffect, useState } from 'react'

// 모든 API는 상대경로 /api/... 로 호출한다 (로컬: Vite 프록시, 운영: CloudFront)
async function api(path, options) {
  const res = await fetch(`/api${path}`, options)
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `요청 실패 (${res.status})`)
  return data
}

export default function App() {
  const [tab, setTab] = useState('student')
  const [status, setStatus] = useState(null)
  const [statusError, setStatusError] = useState('')

  function loadStatus() {
    api('/status')
      .then((data) => { setStatus(data); setStatusError('') })
      .catch(() => setStatusError('백엔드 서버에 연결할 수 없습니다. (로컬: uvicorn 실행 여부 / 운영: ALB·EC2 상태 확인)'))
  }

  useEffect(loadStatus, [tab])

  const s3Ready = status?.s3.configured === true

  return (
    <>
      <h1>과제 제출 시스템</h1>
      <div className="status">
        {statusError && <div className="warn">● {statusError}</div>}
        {status && (
          <>
            <div className={status.db.ok ? 'ok' : 'warn'}>● DB: {status.db.message}</div>
            <div className={s3Ready ? 'ok' : 'warn'}>● S3: {status.s3.message}</div>
          </>
        )}
        {!status && !statusError && <div>연결 상태 확인 중...</div>}
      </div>
      <p className="tabs">
        <button className={tab === 'student' ? 'active' : ''} onClick={() => setTab('student')}>학생</button>{' '}
        <button className={tab === 'admin' ? 'active' : ''} onClick={() => setTab('admin')}>관리자</button>
      </p>
      <hr />
      {tab === 'student' ? <StudentTab s3Ready={s3Ready} /> : <AdminTab s3Ready={s3Ready} />}
    </>
  )
}

function StudentTab({ s3Ready }) {
  const [courses, setCourses] = useState([])
  const [courseId, setCourseId] = useState('')
  const [name, setName] = useState('')
  const [file, setFile] = useState(null)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState('')

  useEffect(() => {
    api('/courses')
      .then((data) => { setCourses(data); if (data.length) setCourseId(String(data[0].id)) })
      .catch((e) => setMsg(e.message))
  }, [])

  async function submit(e) {
    e.preventDefault()
    const form = new FormData()
    form.append('student_name', name)
    if (file) form.append('file', file)
    setBusy(true)
    setMsg('업로드 중...')
    try {
      const data = await api(`/courses/${courseId}/submissions`, { method: 'POST', body: form })
      setMsg(`제출 완료: ${data.filename}`)
      setFile(null)
      e.target.reset()
    } catch (err) {
      setMsg(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!courses.length) return <p>{msg || '개설된 강좌가 없습니다.'}</p>

  return (
    <form onSubmit={submit}>
      <h2>과제 제출</h2>
      <label>강좌
        <select value={courseId} onChange={(e) => setCourseId(e.target.value)}>
          {courses.map((c) => <option key={c.id} value={c.id}>{c.title}</option>)}
        </select>
      </label>
      <label>이름 (학번 포함)
        <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="예) 20301 홍길동" />
      </label>
      <input type="file" onChange={(e) => setFile(e.target.files[0] || null)} />
      <div>
        <button type="submit" disabled={!s3Ready || busy}>제출</button>{' '}
        {!s3Ready && <span className="warn">S3 연결부터 설정하세요.</span>}
      </div>
      {msg && <p className="msg">{msg}</p>}
    </form>
  )
}

function AdminTab({ s3Ready }) {
  const [courses, setCourses] = useState([])
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [selected, setSelected] = useState(null)
  const [submissions, setSubmissions] = useState([])
  const [msg, setMsg] = useState('')

  function loadCourses() {
    api('/courses').then(setCourses).catch((e) => setMsg(e.message))
  }

  useEffect(loadCourses, [])

  async function createCourse(e) {
    e.preventDefault()
    try {
      await api('/courses', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title, description }),
      })
      setTitle('')
      setDescription('')
      setMsg('강좌가 개설되었습니다.')
      loadCourses()
    } catch (err) {
      setMsg(err.message)
    }
  }

  async function showSubmissions(course) {
    try {
      setSubmissions(await api(`/courses/${course.id}/submissions`))
      setSelected(course)
    } catch (err) {
      setMsg(err.message)
    }
  }

  return (
    <>
      <form onSubmit={createCourse}>
        <h2>강좌 개설</h2>
        <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} placeholder="강좌명" />
        <textarea value={description} onChange={(e) => setDescription(e.target.value)} placeholder="설명 (선택)" rows={2} />
        <button type="submit">개설</button>
      </form>
      {msg && <p className="msg">{msg}</p>}

      <h2>강좌 목록</h2>
      <table>
        <thead><tr><th>강좌명</th><th>설명</th><th>개설일</th><th></th></tr></thead>
        <tbody>
          {courses.map((c) => (
            <tr key={c.id}>
              <td>{c.title}</td>
              <td>{c.description}</td>
              <td>{c.created_at}</td>
              <td><button onClick={() => showSubmissions(c)}>제출 보기</button></td>
            </tr>
          ))}
          {!courses.length && <tr><td colSpan={4}>개설된 강좌가 없습니다.</td></tr>}
        </tbody>
      </table>

      {selected && (
        <>
          <h2>제출 목록 - {selected.title}</h2>
          <table>
            <thead><tr><th>이름</th><th>파일명</th><th>제출시각</th><th></th></tr></thead>
            <tbody>
              {submissions.map((s) => (
                <tr key={s.id}>
                  <td>{s.student_name}</td>
                  <td>{s.filename}</td>
                  <td>{s.created_at}</td>
                  <td>{s3Ready ? <a href={`/api/submissions/${s.id}/download`}>다운로드</a> : 'S3 미연결'}</td>
                </tr>
              ))}
              {!submissions.length && <tr><td colSpan={4}>제출된 과제가 없습니다.</td></tr>}
            </tbody>
          </table>
        </>
      )}
    </>
  )
}
