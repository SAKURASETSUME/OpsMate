package com.opsmate.assistant;

import com.opsmate.infrastructure.ApiFailure;
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.Charset;
import java.nio.charset.StandardCharsets;

/** Decodes text for the model while the attachment store retains the original bytes. */
final class AttachmentText {
    private static final Charset GB18030 = Charset.forName("GB18030");

    private AttachmentText() {}

    static String decode(byte[] bytes) {
        try {
            if (startsWith(bytes, 0xef, 0xbb, 0xbf)) {
                return decode(bytes, 3, StandardCharsets.UTF_8);
            }
            if (startsWith(bytes, 0xff, 0xfe)) {
                return decode(bytes, 2, StandardCharsets.UTF_16LE);
            }
            if (startsWith(bytes, 0xfe, 0xff)) {
                return decode(bytes, 2, StandardCharsets.UTF_16BE);
            }
            try {
                return decode(bytes, 0, StandardCharsets.UTF_8);
            } catch (CharacterCodingException invalidUtf8) {
                return decode(bytes, 0, GB18030);
            }
        } catch (CharacterCodingException invalid) {
            throw new ApiFailure(415, "无法识别文本附件编码，支持 UTF-8、GBK/GB18030 和带 BOM 的 UTF-16");
        }
    }

    private static String decode(byte[] bytes, int offset, Charset charset) throws CharacterCodingException {
        String text = charset.newDecoder().decode(ByteBuffer.wrap(bytes, offset, bytes.length - offset)).toString();
        if (text.codePoints().anyMatch(value -> Character.isISOControl(value)
                && value != '\t' && value != '\n' && value != '\r' && value != '\f' && value != 0x1b)) {
            throw new CharacterCodingException();
        }
        return text;
    }

    private static boolean startsWith(byte[] bytes, int... prefix) {
        if (bytes.length < prefix.length) {
            return false;
        }
        for (int index = 0; index < prefix.length; index++) {
            if (Byte.toUnsignedInt(bytes[index]) != prefix[index]) {
                return false;
            }
        }
        return true;
    }
}
