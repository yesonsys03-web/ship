type DropZoneProps = {
  folderPath: string;
  isBusy: boolean;
};

export function DropZone({ folderPath, isBusy }: DropZoneProps) {
  return (
    <section className="drop-zone">
      <h2>선적 폴더를 이 창에 놓으세요</h2>
      <p>{folderPath || '폴더를 놓으면 내부 파일 목록을 자동으로 읽어옵니다.'}</p>
      {isBusy && <span className="pulse">읽는 중...</span>}
    </section>
  );
}
