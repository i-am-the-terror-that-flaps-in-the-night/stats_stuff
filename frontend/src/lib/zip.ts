// A ZIP writer, so "download everything" is one file instead of ten prompts.
//
// WHY THIS EXISTS RATHER THAN A LIBRARY
//   The same reason lib/svgExport.ts writes its own PDF: the archive this needs
//   to produce is the simplest one the format allows, and a dependency for it
//   would cost more in bundle size on a cold Render start than the ninety lines
//   below. There is no compression here at all — every entry is STORED. The
//   payloads are PDFs and PNGs, both already compressed, so deflating them
//   would spend real CPU to save a percent or two.
//
// WHAT A READER HAS TO ACCEPT
//   Three structures, in this order: a local header immediately followed by its
//   bytes, once per file; then a central directory repeating that metadata with
//   a pointer back to each local header; then an end-of-central-directory
//   record saying how many entries there are and where the directory starts.
//   The pointers are absolute byte offsets, which is why this assembles into
//   one buffer and measures as it goes rather than concatenating blobs — the
//   offsets have to be known before the directory can be written.

/** One file in the archive. */
export interface ZipEntry {
  /** Path inside the archive. Forward slashes make folders. */
  name: string;
  data: Uint8Array;
}

const LOCAL_SIG = 0x04034b50;
const CENTRAL_SIG = 0x02014b50;
const END_SIG = 0x06054b50;
/** Bit 11: the filename is UTF-8 rather than the format's ancient code page. */
const UTF8_FLAG = 0x0800;
const STORED = 0;
const VERSION = 20; // 2.0 — the floor for a stored entry every reader handles

const CRC_TABLE = ((): Uint32Array => {
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let bit = 0; bit < 8; bit++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[i] = c >>> 0;
  }
  return table;
})();

/**
 * CRC-32 of a byte string, as ZIP defines it.
 *
 * Every entry carries one and readers check it, so a wrong value here produces
 * an archive that opens, lists its contents, and then refuses to extract.
 */
export function crc32(bytes: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < bytes.length; i++) {
    c = (CRC_TABLE[(c ^ (bytes[i] ?? 0)) & 0xff] ?? 0) ^ (c >>> 8);
  }
  return (c ^ 0xffffffff) >>> 0;
}

/** MS-DOS packed date and time — the only timestamp the base format has. */
export function dosStamp(when: Date): { time: number; date: number } {
  // Seconds get one bit fewer than they need, so the format stores them in
  // units of two. Years are counted from 1980; anything earlier cannot be
  // represented, so it clamps rather than writing a negative year.
  const year = Math.max(1980, when.getFullYear());
  return {
    time:
      (when.getHours() << 11) | (when.getMinutes() << 5) | (when.getSeconds() >> 1),
    date: ((year - 1980) << 9) | ((when.getMonth() + 1) << 5) | when.getDate(),
  };
}

/**
 * Build a ZIP archive. Returns the raw bytes; the caller wraps them in a Blob.
 *
 * `when` is a parameter rather than a call to `new Date()` inside so a test can
 * ask for the same bytes twice.
 */
export function zipBytes(entries: ZipEntry[], when: Date = new Date()): Uint8Array {
  const encoder = new TextEncoder();
  const stamp = dosStamp(when);
  const named = entries.map((entry) => ({
    ...entry,
    nameBytes: encoder.encode(entry.name),
    crc: crc32(entry.data),
  }));

  const LOCAL_HEAD = 30;
  const CENTRAL_HEAD = 46;
  const END = 22;

  const localSize = named.reduce(
    (sum, e) => sum + LOCAL_HEAD + e.nameBytes.length + e.data.length,
    0,
  );
  const centralSize = named.reduce(
    (sum, e) => sum + CENTRAL_HEAD + e.nameBytes.length,
    0,
  );

  const out = new Uint8Array(localSize + centralSize + END);
  const view = new DataView(out.buffer);
  let at = 0;

  const u32 = (value: number): void => {
    view.setUint32(at, value, true);
    at += 4;
  };
  const u16 = (value: number): void => {
    view.setUint16(at, value, true);
    at += 2;
  };
  const bytes = (source: Uint8Array): void => {
    out.set(source, at);
    at += source.length;
  };

  const offsets: number[] = [];
  for (const entry of named) {
    offsets.push(at);
    u32(LOCAL_SIG);
    u16(VERSION);
    u16(UTF8_FLAG);
    u16(STORED);
    u16(stamp.time);
    u16(stamp.date);
    u32(entry.crc);
    u32(entry.data.length); // compressed size — the same, nothing is deflated
    u32(entry.data.length);
    u16(entry.nameBytes.length);
    u16(0); // no extra field
    bytes(entry.nameBytes);
    bytes(entry.data);
  }

  const centralAt = at;
  named.forEach((entry, index) => {
    u32(CENTRAL_SIG);
    u16(VERSION); // version made by
    u16(VERSION); // version needed
    u16(UTF8_FLAG);
    u16(STORED);
    u16(stamp.time);
    u16(stamp.date);
    u32(entry.crc);
    u32(entry.data.length);
    u32(entry.data.length);
    u16(entry.nameBytes.length);
    u16(0); // extra
    u16(0); // comment
    u16(0); // disk number
    u16(0); // internal attributes
    u32(0); // external attributes
    u32(offsets[index] ?? 0);
    bytes(entry.nameBytes);
  });

  // Measured BEFORE the end record is written. Reading `at` further down would
  // include the twelve bytes of the record itself, which puts the directory's
  // stated end past its real one -- an archive most readers still open, and one
  // that some refuse, for a reason nothing here would report.
  const directoryBytes = at - centralAt;

  u32(END_SIG);
  u16(0); // this disk
  u16(0); // disk holding the directory
  u16(named.length);
  u16(named.length);
  u32(directoryBytes);
  u32(centralAt);
  u16(0); // no archive comment

  return out;
}

/** The archive as a Blob, ready to hand to a download. */
export function zipBlob(entries: ZipEntry[], when?: Date): Blob {
  const buffer = zipBytes(entries, when).buffer as ArrayBuffer;
  return new Blob([buffer], { type: "application/zip" });
}
