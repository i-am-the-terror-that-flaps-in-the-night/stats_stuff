// Tests for the ZIP writer behind "download everything".
//
// Same reasoning as the xref test in svgExport.test.ts: an archive with a wrong
// offset or a wrong checksum is not a visible failure. It downloads, it has a
// plausible size, the operating system shows it as a folder — and then nothing
// comes out of it, or one file comes out corrupt. Nothing in this codebase
// would notice, so the structure is asserted byte for byte.

import { describe, expect, it } from "vitest";
import { crc32, dosStamp, zipBytes } from "./zip";

const FIXED = new Date(2026, 7, 29, 14, 30, 20); // 29 Aug 2026, 14:30:20
const bytes = (text: string): Uint8Array => new TextEncoder().encode(text);

/** Read a little-endian unsigned int, the only way this format stores numbers. */
const u32 = (data: Uint8Array, at: number): number =>
  new DataView(data.buffer, data.byteOffset).getUint32(at, true);
const u16 = (data: Uint8Array, at: number): number =>
  new DataView(data.buffer, data.byteOffset).getUint16(at, true);

describe("crc32", () => {
  it("matches the published check value", () => {
    // The standard CRC-32 conformance vector: "123456789" -> 0xCBF43926.
    expect(crc32(bytes("123456789"))).toBe(0xcbf43926);
  });

  it("is zero for no bytes at all", () => {
    expect(crc32(new Uint8Array(0))).toBe(0);
  });

  it("changes when a single byte changes", () => {
    expect(crc32(bytes("figure-a"))).not.toBe(crc32(bytes("figure-b")));
  });
});

describe("dosStamp", () => {
  it("packs the date into the format's bit fields", () => {
    const { time, date } = dosStamp(FIXED);
    expect((date >> 9) + 1980).toBe(2026);
    expect((date >> 5) & 0x0f).toBe(8); // August
    expect(date & 0x1f).toBe(29);
    expect(time >> 11).toBe(14);
    expect((time >> 5) & 0x3f).toBe(30);
    expect((time & 0x1f) * 2).toBe(20); // seconds are stored in units of two
  });

  it("clamps a year the format cannot represent", () => {
    // 1980 is the epoch; anything earlier would write a negative year and
    // produce a date readers reject.
    expect(dosStamp(new Date(1970, 0, 1)).date >> 9).toBe(0);
  });
});

describe("zipBytes", () => {
  const build = (): Uint8Array =>
    zipBytes(
      [
        { name: "alt-distribution.pdf", data: bytes("%PDF-1.4 first") },
        { name: "bmi-density.svg", data: bytes("<svg>second</svg>") },
      ],
      FIXED,
    );

  it("starts with a local header and ends with the directory record", () => {
    const zip = build();
    expect(u32(zip, 0)).toBe(0x04034b50);
    expect(u32(zip, zip.length - 22)).toBe(0x06054b50);
  });

  it("counts its entries in both places the format asks for", () => {
    const zip = build();
    const end = zip.length - 22;
    expect(u16(zip, end + 8)).toBe(2); // entries on this disk
    expect(u16(zip, end + 10)).toBe(2); // entries in total
  });

  it("points the directory at the byte it claims", () => {
    // The check that matters. The end record says where the central directory
    // starts; if that is off by even one byte the archive will not open.
    const zip = build();
    const end = zip.length - 22;
    const directoryAt = u32(zip, end + 16);
    const directorySize = u32(zip, end + 12);
    expect(u32(zip, directoryAt)).toBe(0x02014b50);
    expect(directoryAt + directorySize).toBe(end);
  });

  it("points every directory entry back at its own local header", () => {
    const zip = build();
    const end = zip.length - 22;
    let at = u32(zip, end + 16);
    for (const name of ["alt-distribution.pdf", "bmi-density.svg"]) {
      expect(u32(zip, at)).toBe(0x02014b50);
      const nameLength = u16(zip, at + 28);
      const localAt = u32(zip, at + 42);
      expect(u32(zip, localAt)).toBe(0x04034b50);
      // The local header repeats the name, so the pointer landing on the right
      // entry is checkable rather than merely plausible.
      const localName = new TextDecoder().decode(
        zip.slice(localAt + 30, localAt + 30 + nameLength),
      );
      expect(localName).toBe(name);
      at += 46 + nameLength;
    }
  });

  it("stores the payload uncompressed, with its checksum and both sizes", () => {
    const payload = bytes("%PDF-1.4 first");
    const zip = build();
    expect(u16(zip, 8)).toBe(0); // method 0 = stored
    expect(u32(zip, 14)).toBe(crc32(payload));
    expect(u32(zip, 18)).toBe(payload.length); // compressed
    expect(u32(zip, 22)).toBe(payload.length); // uncompressed
    const nameLength = u16(zip, 26);
    const start = 30 + nameLength;
    expect(new TextDecoder().decode(zip.slice(start, start + payload.length))).toBe(
      "%PDF-1.4 first",
    );
  });

  it("flags its filenames as UTF-8", () => {
    // Without bit 11 a reader is entitled to decode the name as CP437, which
    // turns any non-ASCII figure title into mojibake inside the archive.
    expect(u16(build(), 6) & 0x0800).toBe(0x0800);
  });

  it("survives an empty archive", () => {
    const zip = zipBytes([], FIXED);
    expect(zip.length).toBe(22);
    expect(u32(zip, 0)).toBe(0x06054b50);
    expect(u16(zip, 10)).toBe(0);
  });

  it("is byte-identical for the same input", () => {
    // The timestamp is a parameter for exactly this reason: two bundles of the
    // same figures should not differ only because a second went by.
    expect(build()).toEqual(build());
  });
});
