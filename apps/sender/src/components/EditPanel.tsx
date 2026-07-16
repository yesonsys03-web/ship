type EditPanelProps = {
  note: string;
  onNoteChange: (value: string) => void;
};

export function EditPanel({ note, onNoteChange }: EditPanelProps) {
  return (
    <section className="edit-panel">
      <label>
        전송 메모
        <textarea value={note} onChange={(event) => onNoteChange(event.target.value)} placeholder="필요한 내용을 입력하세요" />
      </label>
    </section>
  );
}
