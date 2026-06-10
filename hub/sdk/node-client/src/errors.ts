export class HubError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "HubError";
  }
}

export class StateError extends HubError {
  constructor(message: string) {
    super(message);
    this.name = "StateError";
  }
}

export class TokenError extends HubError {
  constructor(message: string) {
    super(message);
    this.name = "TokenError";
  }
}

export class JwtError extends HubError {
  constructor(message: string) {
    super(message);
    this.name = "JwtError";
  }
}
