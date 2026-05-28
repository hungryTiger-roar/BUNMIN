import { useCallback, useEffect, useRef, useState } from 'react'
import {
  getGlossary,
  addGlossaryEntry,
  updateGlossaryEntry,
  deleteGlossaryEntry,
  type GlossaryEntry,
} from '@/lib/api'

interface Props {
  onClose: () => void
}

export default function GlossaryModal({ onClose }: Props) {
  const [entries, setEntries] = useState<GlossaryEntry[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // 필터/검색
  const [selectedCategory, setSelectedCategory] = useState<string>('전체')
  const [searchQuery, setSearchQuery] = useState('')

  // 추가/수정 모드
  const [editingEntry, setEditingEntry] = useState<GlossaryEntry | null>(null)
  const [isAdding, setIsAdding] = useState(false)
  const [formKorean, setFormKorean] = useState('')
  const [formEnglish, setFormEnglish] = useState('')
  const [formCategory, setFormCategory] = useState('일반')
  const [saving, setSaving] = useState(false)
  const koreanInputRef = useRef<HTMLInputElement>(null)

  // 추가/수정 폼 열릴 때 한글 입력창에 포커스
  useEffect(() => {
    if (isAdding || editingEntry) {
      // 여러 번 시도해서 확실히 포커스
      const focus = () => koreanInputRef.current?.focus()
      focus()
      const t1 = setTimeout(focus, 50)
      const t2 = setTimeout(focus, 150)
      return () => {
        clearTimeout(t1)
        clearTimeout(t2)
      }
    }
  }, [isAdding, editingEntry])

  // 에러 메시지 3초 후 자동 해제
  useEffect(() => {
    if (error) {
      const timer = setTimeout(() => setError(null), 3000)
      return () => clearTimeout(timer)
    }
  }, [error])

  const loadGlossary = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await getGlossary()
      setEntries(data.entries)
      const newCategories = ['전체', ...data.categories]
      setCategories(newCategories)
      // 현재 선택된 카테고리가 더 이상 존재하지 않으면 "전체"로 리셋
      setSelectedCategory((prev) =>
        newCategories.includes(prev) ? prev : '전체'
      )
    } catch (err) {
      setError('용어집을 불러오는데 실패했습니다')
      console.error(err)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadGlossary()
  }, [loadGlossary])

  // 필터링된 엔트리
  const filteredEntries = entries.filter((entry) => {
    const matchesCategory = selectedCategory === '전체' || entry.category === selectedCategory
    const matchesSearch =
      !searchQuery ||
      entry.korean.toLowerCase().includes(searchQuery.toLowerCase()) ||
      entry.english.toLowerCase().includes(searchQuery.toLowerCase())
    return matchesCategory && matchesSearch
  })

  const handleAdd = () => {
    setIsAdding(true)
    setEditingEntry(null)
    setFormKorean('')
    setFormEnglish('')
    setFormCategory(selectedCategory === '전체' ? '일반' : selectedCategory)
    setError(null)
  }

  const handleEdit = (entry: GlossaryEntry) => {
    setEditingEntry(entry)
    setIsAdding(false)
    setFormKorean(entry.korean)
    setFormEnglish(entry.english)
    setFormCategory(entry.category)
    setError(null)
  }

  const handleCancel = () => {
    setIsAdding(false)
    setEditingEntry(null)
    setFormKorean('')
    setFormEnglish('')
    setFormCategory('일반')
    setError(null)
  }

  const handleSave = async () => {
    if (!formKorean.trim() || !formEnglish.trim()) {
      setError('한글과 영어를 모두 입력해주세요')
      return
    }

    setSaving(true)
    setError(null)
    try {
      if (isAdding) {
        await addGlossaryEntry({
          korean: formKorean.trim(),
          english: formEnglish.trim(),
          category: formCategory,
        })
      } else if (editingEntry) {
        await updateGlossaryEntry(editingEntry.korean, {
          korean: formKorean.trim(),
          english: formEnglish.trim(),
          category: formCategory,
        })
      }
      await loadGlossary()
      handleCancel()
    } catch (err) {
      setError(err instanceof Error ? err.message : '저장에 실패했습니다')
    } finally {
      setSaving(false)
    }
  }

  const [deleteTarget, setDeleteTarget] = useState<GlossaryEntry | null>(null)

  const handleDeleteClick = (entry: GlossaryEntry) => {
    setDeleteTarget(entry)
  }

  const handleDeleteConfirm = async () => {
    if (!deleteTarget) return
    const { korean } = deleteTarget
    setDeleteTarget(null)

    try {
      await deleteGlossaryEntry(korean)
      // 로컬 상태 즉시 업데이트 (카테고리는 유지)
      setEntries((prev) => prev.filter((e) => e.korean !== korean))
    } catch (err) {
      setError(err instanceof Error ? err.message : '삭제에 실패했습니다')
    }
  }

  const handleDeleteCancel = () => {
    setDeleteTarget(null)
  }

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/70">
      <div className="bg-white dark:bg-gray-800 rounded-xl shadow-2xl w-full max-w-3xl mx-4 max-h-[85vh] flex flex-col border border-gray-200 dark:border-gray-700">
        {/* 헤더 */}
        <div className="flex items-center justify-between p-4 border-b border-gray-200 dark:border-gray-700">
          <h2 className="text-lg font-semibold text-gray-900 dark:text-white">
            번역 용어집 관리
          </h2>
          <button
            onClick={onClose}
            className="p-1 text-gray-500 hover:text-gray-700 dark:text-gray-400 dark:hover:text-gray-200"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* 툴바: 카테고리 필터 + 검색 + 추가 버튼 */}
        <div className="flex flex-wrap items-center gap-3 p-4 border-b border-gray-200 dark:border-gray-700">
          <select
            value={selectedCategory}
            onChange={(e) => setSelectedCategory(e.target.value)}
            className="px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
          >
            {categories.map((cat) => (
              <option key={cat} value={cat}>{cat}</option>
            ))}
          </select>

          <div className="flex-1 min-w-[200px]">
            <input
              type="text"
              placeholder="검색 (한글 또는 영어)"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white placeholder-gray-400"
            />
          </div>

          <button
            onClick={handleAdd}
            className="flex items-center gap-1 px-3 py-1.5 text-sm bg-blue-600 hover:bg-blue-700 text-white rounded-lg transition-colors"
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            용어 추가
          </button>
        </div>

        {/* 추가 폼 (새 용어 추가시에만 상단에 표시) */}
        {isAdding && (
          <div className="p-4 bg-blue-50 dark:bg-blue-900/20 border-b border-gray-200 dark:border-gray-700">
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex-1 min-w-[150px]">
                <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">한글</label>
                <input
                  ref={koreanInputRef}
                  type="text"
                  value={formKorean}
                  onChange={(e) => setFormKorean(e.target.value)}
                  placeholder="예: 경제학"
                  autoFocus
                  className="w-full px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                />
              </div>
              <div className="flex-1 min-w-[150px]">
                <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">영어</label>
                <input
                  type="text"
                  value={formEnglish}
                  onChange={(e) => setFormEnglish(e.target.value)}
                  placeholder="예: economics"
                  className="w-full px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                />
              </div>
              <div className="w-32">
                <label className="block text-xs text-gray-600 dark:text-gray-400 mb-1">카테고리</label>
                <input
                  type="text"
                  value={formCategory}
                  onChange={(e) => setFormCategory(e.target.value)}
                  placeholder="예: 경제학"
                  className="w-full px-3 py-1.5 text-sm border border-gray-300 dark:border-gray-600 rounded-lg bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                />
              </div>
              <div className="flex gap-2">
                <button
                  onClick={handleSave}
                  disabled={saving}
                  className="px-3 py-1.5 text-sm bg-green-600 hover:bg-green-700 text-white rounded-lg disabled:opacity-50 transition-colors"
                >
                  {saving ? '저장 중...' : '저장'}
                </button>
                <button
                  onClick={handleCancel}
                  className="px-3 py-1.5 text-sm bg-gray-500 hover:bg-gray-600 text-white rounded-lg transition-colors"
                >
                  취소
                </button>
              </div>
            </div>
          </div>
        )}

        {/* 에러 메시지 */}
        {error && (
          <div className="px-4 py-2 bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm">
            {error}
          </div>
        )}

        {/* 용어 목록 */}
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center h-40 text-gray-500">
              로딩 중...
            </div>
          ) : filteredEntries.length === 0 ? (
            <div className="flex items-center justify-center h-40 text-gray-500">
              {searchQuery ? '검색 결과가 없습니다' : '등록된 용어가 없습니다'}
            </div>
          ) : (
            <table className="w-full">
              <thead className="bg-gray-50 dark:bg-gray-700 sticky top-0">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">한글</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">영어</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-500 dark:text-gray-400 uppercase">카테고리</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-500 dark:text-gray-400 uppercase w-24">작업</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
                {filteredEntries.map((entry) => (
                  editingEntry?.id === entry.id ? (
                    // 인라인 수정 모드
                    <tr key={entry.id} className="bg-blue-50 dark:bg-blue-900/20">
                      <td className="px-4 py-2">
                        <input
                          ref={koreanInputRef}
                          type="text"
                          value={formKorean}
                          onChange={(e) => setFormKorean(e.target.value)}
                          className="w-full px-2 py-1 text-sm border border-blue-300 dark:border-blue-600 rounded bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                        />
                      </td>
                      <td className="px-4 py-2">
                        <input
                          type="text"
                          value={formEnglish}
                          onChange={(e) => setFormEnglish(e.target.value)}
                          className="w-full px-2 py-1 text-sm border border-blue-300 dark:border-blue-600 rounded bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                        />
                      </td>
                      <td className="px-4 py-2">
                        <input
                          type="text"
                          value={formCategory}
                          onChange={(e) => setFormCategory(e.target.value)}
                          className="w-full px-2 py-1 text-sm border border-blue-300 dark:border-blue-600 rounded bg-white dark:bg-gray-700 text-gray-900 dark:text-white"
                        />
                      </td>
                      <td className="px-4 py-2 text-right whitespace-nowrap">
                        <button
                          onClick={handleSave}
                          disabled={saving}
                          className="px-2 py-1 text-xs bg-green-600 hover:bg-green-700 text-white rounded disabled:opacity-50 transition-colors"
                        >
                          {saving ? '...' : '저장'}
                        </button>
                        <button
                          onClick={handleCancel}
                          className="px-2 py-1 text-xs bg-gray-500 hover:bg-gray-600 text-white rounded ml-1 transition-colors"
                        >
                          취소
                        </button>
                      </td>
                    </tr>
                  ) : (
                    // 일반 표시 모드
                    <tr key={entry.id} className="hover:bg-gray-50 dark:hover:bg-gray-700/50">
                      <td className="px-4 py-2 text-sm text-gray-900 dark:text-white">{entry.korean}</td>
                      <td className="px-4 py-2 text-sm text-gray-700 dark:text-gray-300">{entry.english}</td>
                      <td className="px-4 py-2 text-sm text-gray-500 dark:text-gray-400">{entry.category}</td>
                      <td className="px-4 py-2 text-right">
                        <button
                          onClick={() => handleEdit(entry)}
                          className="p-1 text-blue-600 hover:text-blue-800 dark:text-blue-400"
                          title="수정"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                          </svg>
                        </button>
                        <button
                          onClick={() => handleDeleteClick(entry)}
                          className="p-1 text-red-600 hover:text-red-800 dark:text-red-400 ml-1"
                          title="삭제"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                          </svg>
                        </button>
                      </td>
                    </tr>
                  )
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* 푸터 */}
        <div className="flex items-center justify-between p-4 border-t border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-700/50">
          <span className="text-sm text-gray-500 dark:text-gray-400">
            총 {filteredEntries.length}개 용어
            {selectedCategory !== '전체' && ` (${selectedCategory})`}
          </span>
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm bg-gray-600 hover:bg-gray-700 text-white rounded-lg transition-colors"
          >
            닫기
          </button>
        </div>
      </div>

      {/* 삭제 확인 모달 */}
      {deleteTarget && (
        <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/50">
          <div className="bg-white dark:bg-gray-800 rounded-lg shadow-xl p-6 mx-4 max-w-sm w-full">
            <p className="text-gray-900 dark:text-white text-center mb-6">
              '{deleteTarget.korean}' 용어를 정말 삭제하시겠습니까?
            </p>
            <div className="flex justify-center gap-3">
              <button
                onClick={handleDeleteConfirm}
                className="px-4 py-2 text-sm bg-red-600 hover:bg-red-700 text-white rounded-lg transition-colors"
              >
                삭제
              </button>
              <button
                onClick={handleDeleteCancel}
                className="px-4 py-2 text-sm bg-gray-500 hover:bg-gray-600 text-white rounded-lg transition-colors"
              >
                취소
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
