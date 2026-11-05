package com.opsmate.infrastructure;

import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
public class ApiErrors {
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
