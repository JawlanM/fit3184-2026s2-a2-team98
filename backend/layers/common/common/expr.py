"""Placeholder builder for DynamoDB expressions (D-13).

`count`, `status` and `location` are DynamoDB reserved words, and tags like
`feral pig` contain a space. Writing either directly into an expression is a
ValidationException, so every name and value goes through this helper.
"""


class Expr:
    def __init__(self):
        self.names: dict[str, str] = {}
        self.values: dict[str, object] = {}
        self._by_name: dict[str, str] = {}

    def name(self, n: str) -> str:
        if n not in self._by_name:          # same name, same placeholder
            key = f"#n{len(self._by_name)}"
            self._by_name[n] = key
            self.names[key] = n
        return self._by_name[n]

    def value(self, v) -> str:
        key = f":v{len(self.values)}"
        self.values[key] = v
        return key

    def kwargs(self) -> dict:
        """ExpressionAttributeNames/Values, leaving out empty maps (boto3 rejects them)."""
        out = {}
        if self.names:
            out["ExpressionAttributeNames"] = self.names
        if self.values:
            out["ExpressionAttributeValues"] = self.values
        return out
