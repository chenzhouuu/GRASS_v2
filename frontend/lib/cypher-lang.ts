import { StreamLanguage, StringStream } from "@codemirror/language";
import { tags as t } from "@lezer/highlight";

/**
 * Lightweight Cypher syntax highlighting via StreamLanguage.
 * Covers keywords, functions, strings, numbers, comments, labels,
 * relationship types, properties, and parameters.
 */

const cypherKeywords = new Set([
  "match", "optional", "where", "return", "with", "unwind", "order",
  "by", "skip", "limit", "create", "merge", "delete", "detach", "set",
  "remove", "foreach", "in", "case", "when", "then", "else", "end",
  "as", "and", "or", "xor", "not", "is", "null", "true", "false",
  "distinct", "exists", "call", "yield", "union", "all", "any",
  "none", "single", "asc", "ascending", "desc", "descending",
  "on", "starts", "ends", "contains", "count", "collect", "sum",
  "avg", "min", "max", "nodes", "relationships", "type", "id",
  "labels", "keys", "properties", "tostring", "tointeger", "tofloat",
  "toboolean", "size", "length", "head", "tail", "last", "range",
  "reduce", "filter", "extract", "coalesce", "timestamp",
]);

function tokenize(stream: StringStream): string | null {
  // Whitespace
  if (stream.eatSpace()) return null;

  // Line comment
  if (stream.match("//")) {
    stream.skipToEnd();
    return "lineComment";
  }

  // Block comment start
  if (stream.match("/*")) {
    while (!stream.match("*/", true)) {
      if (stream.next() == null) break;
    }
    return "blockComment";
  }

  // Single-quoted string
  if (stream.match("'")) {
    while (!stream.eat("'")) {
      stream.eat("\\");
      if (stream.next() == null) break;
    }
    return "string";
  }

  // Double-quoted string
  if (stream.match('"')) {
    while (!stream.eat('"')) {
      stream.eat("\\");
      if (stream.next() == null) break;
    }
    return "string";
  }

  // Backtick-quoted identifier
  if (stream.match("`")) {
    while (!stream.eat("`")) {
      if (stream.next() == null) break;
    }
    return "string";
  }

  // Parameter ($name)
  if (stream.eat("$")) {
    stream.eatWhile(/[\w]/);
    return "variableName.special";
  }

  // Node label (:Label)
  if (stream.eat(":")) {
    if (stream.eatWhile(/[\w]/)) {
      return "typeName";
    }
    return "punctuation";
  }

  // Number
  if (stream.match(/^-?\d+(\.\d+)?/)) {
    return "number";
  }

  // Operators
  if (stream.match(/^[+\-*/%=<>!]+/)) {
    return "operator";
  }

  // Brackets and punctuation
  if (stream.match(/^[()[\]{},;.|]/)) {
    return "punctuation";
  }

  // Arrow patterns
  if (stream.match(/^-\[/) || stream.match(/^]-?>?/) || stream.match(/^<?-/)) {
    return "operator";
  }

  // Word (keyword or identifier)
  if (stream.eatWhile(/[\w]/)) {
    const word = stream.current().toLowerCase();
    if (cypherKeywords.has(word)) return "keyword";
    return "variableName";
  }

  // Fallback
  stream.next();
  return null;
}

const cypherStreamParser = {
  token: tokenize,
};

export const cypherLanguage = StreamLanguage.define({
  ...cypherStreamParser,
  tokenTable: {
    keyword: t.keyword,
    string: t.string,
    number: t.number,
    lineComment: t.lineComment,
    blockComment: t.blockComment,
    operator: t.operator,
    punctuation: t.punctuation,
    typeName: t.typeName,
    "variableName.special": t.special(t.variableName),
    variableName: t.variableName,
  },
});
