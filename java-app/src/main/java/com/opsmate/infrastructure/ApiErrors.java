package com.opsmate.infrastructure;

import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class ApiErrors {
    @ExceptionHandler(org.springframework.web.multipart.MaxUploadSizeExceededException.class)
    ResponseEntity<?> oversizedUpload(Exception error) {
        return ResponseEntity.status(413).body(Map.of("detail","上传内容超过大小上限，请先裁剪"));
    }
    @ExceptionHandler(org.springframework.http.converter.HttpMessageNotReadableException.class)
    ResponseEntity<?> invalidJson(Exception error) {
        return ResponseEntity.badRequest().body(Map.of("detail","JSON 格式无效"));
    }
    @ExceptionHandler(ApiFailure.class)
    ResponseEntity<?> business(ApiFailure error) {
        return ResponseEntity.status(error.status()).body(Map.of("detail",error.getMessage()));
    }
    @ExceptionHandler(MethodArgumentNotValidException.class)
    ResponseEntity<?> validation(MethodArgumentNotValidException error) {
        var details = error.getBindingResult().getFieldErrors().stream()
            .map(field -> Map.of("loc",java.util.List.of("body",field.getField()),
                "msg",String.valueOf(field.getDefaultMessage()),"type","validation_error")).toList();
        return ResponseEntity.unprocessableEntity().body(Map.of("detail",details));
    }
}
