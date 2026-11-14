/* Memory-to-memory LZX decompression using libmspack's lzxd (as XEX "normal" compression needs). */
#include <stdlib.h>
#include <string.h>
#include "mspack.h"
#include "lzx.h"

struct mem_file { unsigned char* buf; size_t size, pos; };

static struct mspack_file* m_open(struct mspack_system* s, const char* name, int mode) { return (struct mspack_file*)name; }
static void m_close(struct mspack_file* f) {}
static int m_read(struct mspack_file* f, void* buf, int n) {
    struct mem_file* m = (struct mem_file*)f; size_t left = m->size - m->pos;
    if ((size_t)n > left) n = (int)left;
    memcpy(buf, m->buf + m->pos, n); m->pos += n; return n;
}
static int m_write(struct mspack_file* f, void* buf, int n) {
    struct mem_file* m = (struct mem_file*)f; size_t left = m->size - m->pos;
    if ((size_t)n > left) n = (int)left;
    memcpy(m->buf + m->pos, buf, n); m->pos += n; return n;
}
static void* m_alloc(struct mspack_system* s, size_t n) { return malloc(n); }
static void m_free(void* p) { free(p); }
static void m_copy(void* src, void* dst, size_t n) { memcpy(dst, src, n); }
static int m_seek(struct mspack_file* f, off_t o, int mode) { return -1; }
static off_t m_tell(struct mspack_file* f) { return ((struct mem_file*)f)->pos; }
static void m_msg(struct mspack_file* f, const char* fmt, ...) {}

/* Returns 0 on success. */
int lzx_decompress(unsigned char* in, size_t in_size, unsigned char* out, size_t out_size, int window_bits) {
    struct mspack_system sys = { m_open, m_close, m_read, m_write, m_seek, m_tell, m_msg, m_alloc, m_free, m_copy, NULL };
    struct mem_file fi = { in, in_size, 0 }, fo = { out, out_size, 0 };
    struct lzxd_stream* lzx = lzxd_init(&sys, (struct mspack_file*)&fi, (struct mspack_file*)&fo, window_bits, 0, 0x8000, (off_t)out_size, 0);
    if (!lzx) return -1;
    int r = lzxd_decompress(lzx, (off_t)out_size);
    lzxd_free(lzx);
    return r;
}
