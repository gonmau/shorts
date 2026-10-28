# -*- coding: utf-8 -*-
"""성(性)·민감 소재 거르기.
- is_sensitive(item) -> 걸린 단어(없으면 None). 소재 생성 직후(필터)와, 이미 만든 소재 정리(exclude_sensitive.py)에서 같이 씁니다.
- 목록은 아래 두 정규식만 고치면 됩니다. 너무 넓게 걸리는 단어는 빼고, 빠진 단어는 추가하세요."""
import re

KO = (r"성관계|성행위|성적|성인용품|성매매|매춘|윤락|사창|성폭|성추행|성범죄|성기|성욕|섹스|야한|음란|포르노|누드|나체|알몸|토플리스|"
      r"벌거|속옷|처녀성|순결|혼전|첫날밤|할례|피임|콘돔|낙태|임신\s?중절|동성애|동성\s?결혼|성소수|트랜스젠더|LGBT|유흥|퇴폐|"
      r"신부\s?납치|강간|강제\s?결혼|조혼|아동\s?결혼|일부다처|일처다부|"
      r"자살|자해|마약|대마초|코카인|아편|학대|고문|사형|처형|테러|인종\s?차별|혐오|노예|학살|시신|사체|식인종|식인\s?풍습|개고기")
EN = (r"\bsex\w*|erotic\w*|\bporn\w*|\bnude\b|nudity|\bnaked\b|topless|prostitut\w*|brothel|condom|contracepti\w*|abortion|"
      r"\bvirgin\w*|wedding night|circumcis\w*|genital\w*|\brape\w*|molest\w*|incest\w*|polygam\w*|child marriage|bride kidnap\w*|"
      r"\bgay\b|lesbian|homosexual\w*|lgbt\w*|transgender|love motel|adult (toy|video|content|entertainment)|"
      r"suicid\w*|self.harm|\bdrugs?\b|marijuana|cannabis|cocaine|heroin|opium|torture|execution|death penalty|terroris\w*|"
      r"genocide|slavery|racis\w*|hate crime|dog meat|child abuse|domestic violence")

_KO, _EN = re.compile(KO, re.I), re.compile(EN, re.I)
FIELDS = ("country", "label", "topic", "hook", "body", "twist", "narration", "verify_note", "title_line1", "title_line2")


def is_sensitive(item):
    text = " ".join(str(item.get(k, "") or "") for k in FIELDS)
    m = _KO.search(text) or _EN.search(text)
    return m.group(0) if m else None
