"""Planted secrets must never reach the trace store; ordinary text must survive."""

import pytest

from ht2wv.redact import is_private, redact


# Each row names the planted substring and its required replacement label.
PLANTED_SECRETS = [
    ("secret_key='a b c'", "a b c", "SECRET"),
    ("client_secret=clientSecret42", "clientSecret42", "SECRET"),
    ("access_token: accessToken42", "accessToken42", "SECRET"),
    ("refresh_token=refreshToken42", "refreshToken42", "SECRET"),
    ("private_key=privateKey42", "privateKey42", "SECRET"),
    ("APP_CLIENT_SECRET_VALUE='prefixed secret 42'", "prefixed secret 42", "SECRET"),
    ("MY_SECRET_TOKEN=secretToken42", "secretToken42", "SECRET"),
    ("password_value: passwordValue42", "passwordValue42", "SECRET"),
    ('private_key_value="private value 42"', "private value 42", "SECRET"),
    ("--token abcdef123456", "abcdef123456", "SECRET"),
    ("--token=abcdef123456", "abcdef123456", "SECRET"),
    ("--api-key XYZabcdef123456", "XYZabcdef123456", "SECRET"),
    ("--api-key=XYZabcdef123456", "XYZabcdef123456", "SECRET"),
    ("--secret cliSecret42", "cliSecret42", "SECRET"),
    ("--secret=cliSecret42", "cliSecret42", "SECRET"),
    ("--access-token cliAccess42", "cliAccess42", "SECRET"),
    ("--access-token=cliAccess42", "cliAccess42", "SECRET"),
    ("--password cliPassword42", "cliPassword42", "SECRET"),
    ("--password=cliPassword42", "cliPassword42", "SECRET"),
    ("--passwd cliPasswd42", "cliPasswd42", "SECRET"),
    ("--passwd=cliPasswd42", "cliPasswd42", "SECRET"),
    ('run --token "quoted cli value 42" --secret=anotherSecret42', "quoted cli value 42", "SECRET"),
    ('run --token "quoted cli value 42" --secret=anotherSecret42', "anotherSecret42", "SECRET"),
    ("Bearer abcdef12", "abcdef12", "SECRET"),
    ("Bearer abcdef12._~+/=-", "abcdef12._~+/=-", "SECRET"),
    ('Bearer "quotedToken42"', "quotedToken42", "SECRET"),
    ("我的密码：abc123，然后去吃饭", "abc123", "SECRET"),
    ("DB_PASSWORD=x", "x", "SECRET"),
    ("MY_DB_PASSWORD=envPass42", "envPass42", "SECRET"),
    ('export DB_PASSWORD="double quoted pass"', "double quoted pass", "SECRET"),
    ("export MY_DB_PASSWORD='single quoted pass'", "single quoted pass", "SECRET"),
    ("HF_TOKEN=x", "x", "SECRET"),
    ("export HF_TOKEN=hfEnvValue42", "hfEnvValue42", "SECRET"),
    ("MY_HF_TOKEN='hf env value'", "hf env value", "SECRET"),
    ("WANDB_API_KEY=x", "x", "SECRET"),
    ('export WANDB_API_KEY="wandbValue42"', "wandbValue42", "SECRET"),
    ("MY_WANDB_API_KEY=wandbOther42", "wandbOther42", "SECRET"),
    ("我的密码：x", "x", "SECRET"),
    ("密码是abc123456", "abc123456", "SECRET"),
    ("口令：kouling42", "kouling42", "SECRET"),
    ("我的口令是phrase42", "phrase42", "SECRET"),
    ('密码="中文 密码值"', "中文 密码值", "SECRET"),
    ("password: x", "x", "SECRET"),
    ("passwd=hunter22", "hunter22", "SECRET"),
    ("pwd: short42", "short42", "SECRET"),
    ('{"api_key": "jsonValue42", "other": 7}', "jsonValue42", "SECRET"),
    ("api-key: 'yaml value 42'", "yaml value 42", "SECRET"),
    ('{"password": "json pass 42"}', "json pass 42", "SECRET"),
    ('password="quote\\\"inside42"', "inside42", "SECRET"),
    ("--password=standalonePass42", "standalonePass42", "SECRET"),
    ('--password="standalone quoted 42"', "standalone quoted 42", "SECRET"),
    ("export X=hf_abcdefgh12345678", "hf_abcdefgh12345678", "KEY"),
    ("export X=sk-abcdefghijklmnopqrstuv", "sk-abcdefghijklmnopqrstuv", "KEY"),
    ('mysql -p"pass;with&delimiters42"', "pass;with&delimiters42", "SECRET"),
    ("mysql -pfirstCli42 -p secondCli42", "secondCli42", "SECRET"),
    ("mysql -pfirstCli42 -p secondCli42", "firstCli42", "SECRET"),
    ('curl -H "Authorization: Bearer headerValue42"', "headerValue42", "SECRET"),
    ("mysql -pmysqlPass42", "mysqlPass42", "SECRET"),
    ("mysql -p mysqlSpace42", "mysqlSpace42", "SECRET"),
    ("mysql -u root -h db -pmysqlFlags42", "mysqlFlags42", "SECRET"),
    ('mysql -p"mysql quoted 42"', "mysql quoted 42", "SECRET"),
    ("mysql -p 'mysql single 42'", "mysql single 42", "SECRET"),
    ("mysql --password=mysqlLong42", "mysqlLong42", "SECRET"),
    ('mysql --password="mysql long quoted 42"', "mysql long quoted 42", "SECRET"),
    ("mysql --password mysqlLongSpace42", "mysqlLongSpace42", "SECRET"),
    ("sshpass -p sshPass42 ssh user@host", "sshPass42", "SECRET"),
    ("sshpass -p 'ssh quoted 42' ssh user@host", "ssh quoted 42", "SECRET"),
    ('sshpass -p"ssh double 42" ssh user@host', "ssh double 42", "SECRET"),
    ("Authorization: Bearer bearerValue42", "bearerValue42", "SECRET"),
    ("Bearer standaloneValue42", "standaloneValue42", "SECRET"),
    ("authorization: bearer token.With-Dashes_42+/=", "token.With-Dashes_42+/=", "SECRET"),
    ('Authorization: Bearer "quotedBearer42"', "quotedBearer42", "SECRET"),
    ("-----BEGIN PRIVATE KEY-----\nprivatePayload42\nsecondPayload42\n-----END PRIVATE KEY-----", "privatePayload42", "KEY"),
    ("-----BEGIN RSA PRIVATE KEY-----\nrsaPayload42\nmoreRsa42\n-----END RSA PRIVATE KEY-----", "rsaPayload42", "KEY"),
    ("-----BEGIN EC PRIVATE KEY-----\necPayload42\n-----END EC PRIVATE KEY-----", "ecPayload42", "KEY"),
    ("-----BEGIN OPENSSH PRIVATE KEY-----\r\nopensshPayload42\r\nmorePayload42\r\n-----END OPENSSH PRIVATE KEY-----", "opensshPayload42", "KEY"),
    ("-----BEGIN ENCRYPTED PRIVATE KEY-----\nencryptedPayload42\n-----END ENCRYPTED PRIVATE KEY-----", "encryptedPayload42", "KEY"),
    ("aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "SECRET"),
    ("AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "SECRET"),
    ('export AWS_SECRET_ACCESS_KEY="AbCdEfGhIjKlMnOpQrStUvWxYz0123456789+/ab"', "AbCdEfGhIjKlMnOpQrStUvWxYz0123456789+/ab", "SECRET"),
    ("MY_AWS_SECRET_ACCESS_KEY='aws quoted 42'", "aws quoted 42", "SECRET"),
    ("hf_AbCdEfGhIjKlMnOpQrStUvWxYz01234567", "hf_AbCdEfGhIjKlMnOpQrStUvWxYz01234567", "KEY"),
    ("密钥hf_abcdefghijklmnopqrstuvwxyz012345结束", "hf_abcdefghijklmnopqrstuvwxyz012345", "KEY"),
    ("prefix_hf_abcdefgh12345678", "hf_abcdefgh12345678", "KEY"),
    ("+86 138 1234 5678", "+86 138 1234 5678", "PHONE"),
    ("138-1234-5678", "138-1234-5678", "PHONE"),
    ("0086 139 8765 4321", "0086 139 8765 4321", "PHONE"),
    ("+8613812345678", "+8613812345678", "PHONE"),
    ("008613812345678", "008613812345678", "PHONE"),
    ("手机138 1234 5678请联系", "138 1234 5678", "PHONE"),
    ("13812345678", "13812345678", "PHONE"),
    ("https://urluser42:urlpass42@host/path", "urlpass42", "SECRET"),
    ("https://urluser42:urlpass42@host/path", "urluser42", "SECRET"),
    ("postgresql://dbuser42:encoded%40pass42@db/app", "encoded%40pass42", "SECRET"),
    ("https://user:sk-abcdefghijklmnopqrstuv@host", "sk-abcdefghijklmnopqrstuv", "SECRET"),
    ("sk-abcdefghijklmnopqrstuv", "sk-abcdefghijklmnopqrstuv", "KEY"),
    ("密钥sk-abcdefghijklmnopqrstuv结束", "sk-abcdefghijklmnopqrstuv", "KEY"),
    ("prefix_ghp_abcdefghijklmnopqrstuv", "ghp_abcdefghijklmnopqrstuv", "KEY"),
    ("AKIAIOSFODNN7EXAMPLE", "AKIAIOSFODNN7EXAMPLE", "KEY"),
    ("AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz12345", "AIzaSyAbCdEfGhIjKlMnOpQrStUvWxYz12345", "KEY"),
    ("eyJabcdefghijk.abcdefghijk.abcdefghi", "eyJabcdefghijk.abcdefghijk.abcdefghi", "JWT"),
    ("令牌eyJabcdefghijk.abcdefghijk.abcdefghi结束", "eyJabcdefghijk.abcdefghijk.abcdefghi", "JWT"),
    ("mail a.b+tag@example.com", "a.b+tag@example.com", "EMAIL"),
    ("secret@example.com", "secret@example.com", "EMAIL"),
    ("4111111111111111", "4111111111111111", "CARD"),
    ("4111 1111 1111 1111", "4111 1111 1111 1111", "CARD"),
    ("11010519491231002X", "11010519491231002X", "CNID"),
    ("110105194912310021", "110105194912310021", "CNID"),
]


@pytest.mark.parametrize("text,secret,label", PLANTED_SECRETS)
def test_planted_secret_is_blocked(text, secret, label):
    out = redact(text)
    assert secret not in out
    assert f"[{label}]" in out


MUST_SURVIVE = [
    "token_count: 512",
    "max_tokens: 512",
    "num_tokens=3",
    "APP_TOKEN_COUNT: 512",
    "the bearer of bad news",
    "the Bearer of bad news",
    "bearer abcdef123456",
    "BEARER abcdef123456",
    "Bearer abcdefg",
    "Bearer bad!news",
    "--token-file path",
    "--password-file path",
    "--token-file=path --password-file=path",
    "password reset flow",
    "the token count is 512",
    "token_count=512",
    "password_reset_flow=enabled",
    '{"api_key_docs": "readme"}',
    "tokenizer",
    "secret sauce",
    "密码学课程",
    "口令管理课程",
    "git SHA abcdef0123456789abcdef0123456789abcdef01",
    "git SHA 0123456789012345678901234567890123456789",
    "UUID 123e4567-e89b-12d3-a456-426614174000",
    "version 1.2.3 and Python 3.14.0",
    "2026-10-13 14:03:22",
    r"D:\work\reports\metrics_W41.csv",
    "mysql -u root -h db",
    "mysql -p -h db",
    "mysql --password",
    "mysql --password -h db",
    "mysql -P 3306 -u root",
    "sshpass -p",
    "sshpass -e ssh user@host",
    "ordinary numbers 12345 and 512",
    "api_key documentation",
    "password:",
    "Bearer",
    "https://host/path?version=1.2.3",
    "-----BEGIN PUBLIC KEY-----\npublicPayload42\n-----END PUBLIC KEY-----",
    "hf_dataset and hf_tokenizer",
]


@pytest.mark.parametrize("text", MUST_SURVIVE)
def test_ordinary_text_survives(text):
    assert redact(text) == text


@pytest.mark.parametrize("text,expected", [
    ("secret_key='a b c'", "secret_key='[SECRET]'"),
    ("APP_CLIENT_SECRET_VALUE=x", "APP_CLIENT_SECRET_VALUE=[SECRET]"),
    ("run --token abcdef123456 --passwd=another42", "run --token [SECRET] --passwd=[SECRET]"),
    ("我的密码：abc123，然后去吃饭", "我的密码：[SECRET]，然后去吃饭"),
    ("密码=abc123接下来去吃饭", "密码=[SECRET]接下来去吃饭"),
    ("secret_key=abc123。后续说明", "secret_key=[SECRET]。后续说明"),
    ("access_token=abc123；后续说明", "access_token=[SECRET]；后续说明"),
    ("private_key=abc123\u3000后续说明", "private_key=[SECRET]\u3000后续说明"),
    ("refresh_token=abc123\u3400后续说明", "refresh_token=[SECRET]\u3400后续说明"),
    ("password_value=abc123\uf900后续说明", "password_value=[SECRET]\uf900后续说明"),
    ("secret_value=abc123\U00020000后续说明", "secret_value=[SECRET]\U00020000后续说明"),
    ('secret_key="中文 密码值"，后续说明', 'secret_key="[SECRET]"，后续说明'),
    ("MY_DB_PASSWORD=x", "MY_DB_PASSWORD=[SECRET]"),
    ('export HF_TOKEN="a b"', 'export HF_TOKEN="[SECRET]"'),
    ("aws_secret_access_key = x", "aws_secret_access_key = [SECRET]"),
    ('{"api_key": "x", "other": 7}', '{"api_key": "[SECRET]", "other": 7}'),
    ("口令：x", "口令：[SECRET]"),
    ("密码是abc123456", "密码是[SECRET]"),
    ("mysql -u root -p x -h db", "mysql -u root -p [SECRET] -h db"),
    ("Authorization: Bearer abc42", "Authorization: Bearer [SECRET]"),
    ("https://user:pass@host/path", "https://[SECRET]@host/path"),
])
def test_secret_context_is_preserved(text, expected):
    assert redact(text) == expected


def test_multiple_secrets_and_pem_ordering():
    text = ("DB_PASSWORD=firstPass42 HF_TOKEN=secondToken42\n"
            "-----BEGIN RSA PRIVATE KEY-----\npassword: pemPass42\n"
            "sk-abcdefghijklmnopqrstuv\n-----END RSA PRIVATE KEY-----\n"
            "https://user42:pass42@host")
    out = redact(text)
    for secret in ("firstPass42", "secondToken42", "pemPass42",
                   "sk-abcdefghijklmnopqrstuv", "user42", "pass42"):
        assert secret not in out
    assert out == "DB_PASSWORD=[SECRET] HF_TOKEN=[SECRET]\n[KEY]\nhttps://[SECRET]@host"


def test_extra_patterns_and_private_matching_are_unchanged():
    assert redact("prefix secret@example.com", ["prefix"]) == "[REDACTED] [EMAIL]"
    assert redact("", [".*"]) == ""
    assert is_private("chrome.exe", "Sign in - 1Password", ["1password"])
    assert is_private("PRIVATE.exe", "ordinary title", ["private"])
    assert not is_private("editor.exe", "public file", ["private"])
