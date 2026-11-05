package com.opsmate.infrastructure;

public class ApiFailure extends RuntimeException {
    private final int status;
    public ApiFailure(int status, String message) {
        super(message);
        this.status = status;
    }
    public int status() { return status; }
}
