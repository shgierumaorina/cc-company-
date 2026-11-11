"""文字起こしに使った音声そのものを保存・再生する。

番組の配信元は、ダウンロードのたびに違う広告を差し込むことがあり、そのまま再生すると
文字起こしと時刻がずれる。そこで、文字起こしと同じ音声を小さく圧縮して保存しておく。
クラウドではTursoの表 en_audio に分割して保存（日記の表には触れない）、PCでは data/ に保存。
"""
import base64
import os
import shutil

from . import store, turso

CHUNK = 192 * 1024        # 1行あたりのバイト数
WRITE_BATCH = 6           # 1回の通信で書き込む行数
MAX_RESPONSE = 1024 * 1024  # 1回の再生リクエストで返す最大バイト数（足りない分はブラウザが続きを要求する）
_table_ready = False


def _ensure_table():
    global _table_ready
    if store.CLOUD and not _table_ready:
        turso.execute("CREATE TABLE IF NOT EXISTS en_audio (ep TEXT NOT NULL, idx INTEGER NOT NULL, "
                      "data TEXT NOT NULL, PRIMARY KEY (ep, idx))")
        _table_ready = True


def _local_path(ep_id):
    return os.path.join(store.DATA, "episodes", ep_id, "stored.m4a")


def transcode(src, dst):
    """音声をモノラル・22kHz・32kbpsのAACに圧縮する（38分で約9MB）。"""
    import av
    with av.open(src) as inp:
        stream = next((s for s in inp.streams if s.type == "audio"), None)
        if stream is None:
            raise RuntimeError("このファイルには音声が入っていませんでした")
        with av.open(dst, "w", format="mp4", options={"movflags": "faststart"}) as out:
            ost = out.add_stream("aac", rate=22050)
            ost.codec_context.layout = "mono"
            ost.bit_rate = 32000
            resampler = av.AudioResampler(format="fltp", layout="mono", rate=22050)
            for frame in inp.decode(stream):
                for f in resampler.resample(frame):
                    for packet in ost.encode(f):
                        out.mux(packet)
            for f in resampler.resample(None):
                for packet in ost.encode(f):
                    out.mux(packet)
            for packet in ost.encode(None):
                out.mux(packet)


def save(ep_id, path):
    """圧縮済みの音声ファイルを保存し、サイズを返す。"""
    size = os.path.getsize(path)
    if not store.CLOUD:
        os.makedirs(os.path.dirname(_local_path(ep_id)), exist_ok=True)
        shutil.copyfile(path, _local_path(ep_id))
        return size
    _ensure_table()
    turso.execute("DELETE FROM en_audio WHERE ep = ?", [ep_id])
    with open(path, "rb") as f:
        idx, batch = 0, []
        while True:
            data = f.read(CHUNK)
            if not data:
                break
            batch.append(("INSERT INTO en_audio (ep, idx, data) VALUES (?, ?, ?)",
                          [ep_id, idx, base64.b64encode(data).decode("ascii")]))
            idx += 1
            if len(batch) >= WRITE_BATCH:
                turso.execute_many(batch)
                batch = []
        if batch:
            turso.execute_many(batch)
    return size


def read(ep_id, start, end):
    """start〜end（両端を含む）のバイトを返す。"""
    if not store.CLOUD:
        with open(_local_path(ep_id), "rb") as f:
            f.seek(start)
            return f.read(end - start + 1)
    _ensure_table()
    first, last = start // CHUNK, end // CHUNK
    rows = turso.execute("SELECT data FROM en_audio WHERE ep = ? AND idx BETWEEN ? AND ? ORDER BY idx",
                         [ep_id, first, last])
    data = b"".join(base64.b64decode(r[0]) for r in rows)
    offset = start - first * CHUNK
    return data[offset:offset + (end - start + 1)]


def delete(ep_id):
    if not store.CLOUD:
        if os.path.exists(_local_path(ep_id)):
            os.remove(_local_path(ep_id))
        return
    _ensure_table()
    turso.execute("DELETE FROM en_audio WHERE ep = ?", [ep_id])
