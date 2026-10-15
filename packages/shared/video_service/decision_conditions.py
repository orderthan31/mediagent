"""Approved WF06 A: two fixed predicates, exactly one match, no fallback/eval."""
from .decision_adapter import structured_result

FIELDS = ['label', 'confidence']
OPS = ['eq', 'gte', 'lte']
VALUES = ['pass', 'review', 'reject', '0', '0.5', '0.7', '0.9', '1']
OPTIONS = {f'{port}_{key}': values for port in ('a', 'b') for key, values in [('field', FIELDS), ('op', OPS), ('value', VALUES if port == 'a' else ['reject', 'pass', 'review', '0', '0.5', '0.7', '0.9', '1'])]}


class DecisionConditionError(ValueError):
    pass


def conditions(options):
    result = {}
    for port in ('a', 'b'):
        field = options.get(port + '_field', 'label')
        op = options.get(port + '_op', 'eq')
        value = options.get(port + '_value', 'pass' if port == 'a' else 'reject')
        if (field not in FIELDS or op not in OPS or not isinstance(value, str)
                or field == 'label' and (op != 'eq' or value not in {'pass', 'review', 'reject'})
                or field == 'confidence' and value not in {'0', '0.5', '0.7', '0.9', '1'}):
            raise DecisionConditionError('조건은 label eq(pass/review/reject) 또는 confidence eq/gte/lte(지원 기준값)만 허용합니다.')
        result[port] = {'field': field, 'op': op, 'value': value if field == 'label' else float(value)}
    return result


def evaluate(judgment, options):
    judgment = structured_result(judgment)
    predicates = conditions(options)
    matches = {}
    for port, condition in predicates.items():
        actual, expected = judgment[condition['field']], condition['value']
        matches[port] = actual == expected if condition['op'] == 'eq' else actual >= expected if condition['op'] == 'gte' else actual <= expected
    selected = [port for port, matched in matches.items() if matched]
    if len(selected) != 1:
        raise DecisionConditionError('조건 둘 다 일치' if selected else '조건 둘 다 불일치')
    return {'conditions': predicates, 'matches': matches, 'selected_port': selected[0]}
