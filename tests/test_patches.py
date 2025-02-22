import hashlib
from itertools import chain

import aiohttp
import botocore
import pytest
from aiohttp.client import ClientResponse
from botocore import retryhandler
from botocore.args import ClientArgsCreator
from botocore.awsrequest import AWSResponse
from botocore.client import BaseClient, ClientCreator, Config
from botocore.configprovider import SmartDefaultsConfigStoreFactory
from botocore.credentials import (
    AssumeRoleCredentialFetcher,
    AssumeRoleProvider,
    AssumeRoleWithWebIdentityCredentialFetcher,
    AssumeRoleWithWebIdentityProvider,
    BotoProvider,
    CachedCredentialFetcher,
    CanonicalNameCredentialSourcer,
    ConfigProvider,
    ContainerProvider,
    CredentialResolver,
    Credentials,
    EnvProvider,
    InstanceMetadataProvider,
    OriginalEC2Provider,
    ProcessProvider,
    ProfileProviderBuilder,
    RefreshableCredentials,
    SharedCredentialProvider,
    SSOCredentialFetcher,
    SSOProvider,
    create_credential_resolver,
    create_mfa_serial_refresher,
    get_credentials,
)
from botocore.discovery import (
    EndpointDiscoveryHandler,
    EndpointDiscoveryManager,
)
from botocore.endpoint import (
    Endpoint,
    EndpointCreator,
    convert_to_response_dict,
)
from botocore.eventstream import EventStream
from botocore.handlers import (
    _looks_like_special_case_error,
    check_for_200_error,
    inject_presigned_url_ec2,
    inject_presigned_url_rds,
    parse_get_bucket_location,
)
from botocore.hooks import EventAliaser, HierarchicalEmitter
from botocore.httpchecksum import (
    AwsChunkedWrapper,
    _apply_request_trailer_checksum,
    _handle_bytes_response,
    apply_request_checksum,
    handle_checksum_body,
)
from botocore.httpsession import URLLib3Session
from botocore.paginate import PageIterator, ResultKeyIterator
from botocore.parsers import (
    PROTOCOL_PARSERS,
    EC2QueryParser,
    JSONParser,
    QueryParser,
    ResponseParserFactory,
    RestJSONParser,
    RestXMLParser,
    create_parser,
)
from botocore.response import StreamingBody, get_response
from botocore.retries import adaptive, special, standard
from botocore.retries.bucket import TokenBucket
from botocore.session import Session, get_session
from botocore.signers import (
    RequestSigner,
    S3PostPresigner,
    add_generate_db_auth_token,
    add_generate_presigned_post,
    add_generate_presigned_url,
    generate_db_auth_token,
    generate_presigned_post,
    generate_presigned_url,
)
from botocore.utils import (
    ContainerMetadataFetcher,
    IMDSFetcher,
    IMDSRegionProvider,
    InstanceMetadataFetcher,
    InstanceMetadataRegionFetcher,
    S3RegionRedirector,
)
from botocore.waiter import (
    NormalizedOperationMethod,
    Waiter,
    create_waiter_with_client,
)
from dill.source import getsource

# This file ensures that our private patches will work going forward.  If a
# method gets updated this will assert and someone will need to validate:
# 1) If our code needs to be updated
# 2) If our minimum botocore version needs to be updated
# 3) If we need to replace the below hash (not backwards compatible) or add
#    to the set

# The follow is for our monkeypatches for read_timeout:
#    github.com/aio-libs/aiobotocore/pull/248
_AIOHTTP_DIGESTS = {
    # for using _body
    ClientResponse: {
        'e178726065b609c69a1c02e8bb78f22efce90792',
        '225e8033bfcff8cccbc2e975d7bd0c7993f14366',
    },
}

# These are guards to our main patches

# !!! README: HOW TO UPDATE THESE !!!
# -----------------------------------
# (tests break with new version of aiohttp/botocore)
#
# 1) Adding support for more versions of aiohttp/botocore
#    In this scenario you need to ensure that aiobotocore supports the changes
#    that broke these tests along with the old versions of the libraries
#    and APPEND to the set of hashes that we support for each object you
#    validated.
# 2) Bumping up the base version of aiohttp/botocore that we support
#    In this scenario ensure aiobotocore supports the new version of the libs
#    and REPLACE all entries with the current hashes with the new libs.

# REPLACE = backwards incompatible change
# APPEND = officially supporting more versions of botocore/aiohttp

# If you're changing these, most likely need to update setup.py as well.
_API_DIGESTS = {
    # args.py
    ClientArgsCreator.get_client_args: {
        '5e5b18cb0b466d3acb2e0ecacbc8dc78de4022fc'
    },
    # client.py
    ClientCreator.create_client: {'3af567fcde81899a3b722d9cafd6a5c78e8ea08c'},
    ClientCreator._create_client_class: {
        'fcecaf8d4f2c1ac3c5d0eb50c573233ef86d641d'
    },
    ClientCreator._register_endpoint_discovery: {
        '483c6c8e035810d1b76110fc1956de76943c2f18'
    },
    ClientCreator._get_client_args: {
        'cc8da937425ba78f715304a82cec346dedb6292e'
    },
    ClientCreator._register_s3_events: {
        'e2ada7e2fcc23f62a414a9dc806a50c0fe6c135c'
    },
    ClientCreator._register_retries: {
        '16d3064142e5f9e45b0094bbfabf7be30183f255'
    },
    ClientCreator._register_v2_adaptive_retries: {
        '665ecd77d36a5abedffb746d83a44bb0a64c660a'
    },
    ClientCreator._register_v2_standard_retries: {
        '9ec4ff68599544b4f46067b3783287862d38fb50'
    },
    ClientCreator._register_legacy_retries: {
        '000b2f2a122602e2e741ec2e89308dc2e2b67329'
    },
    BaseClient._make_api_call: {'ba323d78c89c292efe7fec6b74fe6c258b63d565'},
    BaseClient._make_request: {'cfd8bbf19ea132134717cdf9c460694ddacdbf58'},
    BaseClient._convert_to_request_dict: {
        '2e6eb436e95822f993d70d6127ae11e20689f9c4'
    },
    BaseClient._emit_api_params: {'abd67874dae8d5cd2788412e4699398cb915a119'},
    BaseClient.get_paginator: {'3531d5988aaaf0fbb3885044ccee1a693ec2608b'},
    BaseClient.get_waiter: {'44f0473d993d49ac7502984a7ccee3240b088404'},
    BaseClient.__getattr__: {'3ec17f468f50789fa633d6041f40b66a2f593e77'},
    # config.py
    Config.merge: {'c3dd8c3ffe0da86953ceba4a35267dfb79c6a2c8'},
    Config: {'df1410e13b577bd3c1affa83309c206478907316'},
    # credentials.py
    create_mfa_serial_refresher: {'9b5e98782fcacdcea5899a6d0d29d1b9de348bb0'},
    Credentials.get_frozen_credentials: {
        'eb247f2884aee311bdabba3435e749c3b8589100'
    },
    RefreshableCredentials.__init__: {
        '1a6b83fc845f05feab117ce4fab73b13baed6e3b'
    },
    # We've overridden some properties
    RefreshableCredentials.__dict__['access_key'].fset: {
        'edc4a25baef877a9662f68cd9ccefcd33a81bab7'
    },
    RefreshableCredentials.__dict__['access_key'].fget: {
        'f6c823210099db99dd343d9e1fae6d4eb5aa5fce'
    },
    RefreshableCredentials.__dict__['secret_key'].fset: {
        'b19fe41d66822c72bd6ae2e60de5c5d27367868a'
    },
    RefreshableCredentials.__dict__['secret_key'].fget: {
        '3e27331a037549104b8669e225bbbb2c465a16d4'
    },
    RefreshableCredentials.__dict__['token'].fset: {
        '1f8a308d4bf21e666f8054a0546e91541661da7b'
    },
    RefreshableCredentials.__dict__['token'].fget: {
        '005c1b44b616f37739ce9276352e4e83644d8220'
    },
    RefreshableCredentials._refresh: {
        'd5731d01db2812d498df19b4bd5d7c17519241fe'
    },
    RefreshableCredentials._protected_refresh: {
        '9f8fdb76f41c3b1c64fd4d03d0701504626939e5'
    },
    RefreshableCredentials.get_frozen_credentials: {
        'f661c84a8b759786e011f0b1e8a468a0c6294e36'
    },
    SSOCredentialFetcher: {'ac0cc1f456392f844c7182af635ee87e9fe9cf02'},
    SSOProvider.load: {'f43d79e1520b2a7b7ef85cd537f41e19d4bce806'},
    CachedCredentialFetcher._get_credentials: {
        '02a7d13599d972e3f258d2b53f87eeda4cc3e3a4'
    },
    CachedCredentialFetcher.fetch_credentials: {
        '0dd2986a4cbb38764ec747075306a33117e86c3d'
    },
    CachedCredentialFetcher._get_cached_credentials: {
        'a9f8c348d226e62122972da9ccc025365b6803d6'
    },
    AssumeRoleCredentialFetcher._get_credentials: {
        '5c575634bc0a713c10e5668f28fbfa8779d5a1da'
    },
    AssumeRoleCredentialFetcher._create_client: {
        '27c76f07bd43e665899ca8d21b6ba2038b276fbb'
    },
    # Referenced by AioAssumeRoleWithWebIdentityCredentialFetcher
    AssumeRoleWithWebIdentityCredentialFetcher.__init__: {
        'ab270375dfe425c5e21276590dea690fdbfe40a5'
    },
    AssumeRoleWithWebIdentityCredentialFetcher._get_credentials: {
        '02eba9d4e846474910cb076710070348e395a819'
    },
    AssumeRoleWithWebIdentityCredentialFetcher._assume_role_kwargs: {
        '8fb4fefe8664b7d82a67e0fd6d6812c1c8d92285'
    },
    # Ensure that the load method doesn't do anything we should asyncify
    EnvProvider.load: {'39871a6ec3b3f5d51bc967122793e86b7ca6ed3c'},
    ContainerProvider.__init__: {'ea6aafb2e12730066af930fb5a27f7659c1736a1'},
    ContainerProvider.load: {'57c35569050b45c1e9e33fcdb3b49da9e342fdcf'},
    ContainerProvider._retrieve_or_fail: {
        '7c14f1cdee07217f847a71068866bdd10c3fa0fa'
    },
    ContainerProvider._create_fetcher: {
        '935ae28fdb1c76f419523d4030265f8c4d9d0b00'
    },
    InstanceMetadataProvider.load: {
        '2016921ddb86cab5ec699ab217e847a300745990'
    },
    ProfileProviderBuilder._create_process_provider: {
        'c5eea47bcfc449a6d73a9892bd0e1897f6be0c20'
    },
    ProfileProviderBuilder._create_shared_credential_provider: {
        '33f99c6a0ef71a92b0c52ccc59c8ca7e33fa0890'
    },
    ProfileProviderBuilder._create_config_provider: {
        'f9a40d4211f6e663ba2ae9682fba5306152178c5'
    },
    ProfileProviderBuilder._create_web_identity_provider: {
        '478745fa6779a7c69fe9441d89d3e921438e3a59'
    },
    ProfileProviderBuilder._create_sso_provider: {
        '258e6d07bdf40ea2c7551bae0cd6e1ab58e4e502'
    },
    ConfigProvider.load: {'d0714da9f1f54cebc555df82f181c4913ce97258'},
    SharedCredentialProvider.load: {
        '8a17d992e2a90ebc0e07ba5a5dfef2b725367496'
    },
    ProcessProvider.__init__: {'2e870ec0c6b0bc8483fa9b1159ef68bbd7a12c56'},
    ProcessProvider.load: {'6866e1d3abbde7a14e83aea28cc49377faaca84b'},
    ProcessProvider._retrieve_credentials_using: {
        'c12acda42ddc5dfd73946adce8c155295f8c6b88'
    },
    CredentialResolver.load_credentials: {
        'ef31ba8817f84c1f61f36259da1cc6e597b8625a'
    },
    AssumeRoleWithWebIdentityProvider.load: {
        '8f48f6cadf08a09cf5a22b1cc668e60bc4ea389d'
    },
    AssumeRoleWithWebIdentityProvider._assume_role_with_web_identity: {
        '32c9d720ab5f12054583758b5cd5d287f652ccd3'
    },
    AssumeRoleProvider.load: {'ee9ddb43e25eb1105185253c0963a2f5add49a95'},
    AssumeRoleProvider._load_creds_via_assume_role: {
        '85116d63561c9a8bfdfffdbf837b8a7e61b47ea3'
    },
    AssumeRoleProvider._resolve_source_credentials: {
        '105c0c011e23d76a3b8bd3d9b91b6d945c8307a1'
    },
    AssumeRoleProvider._resolve_credentials_from_profile: {
        'a87ece979f8c94c1afd5801156e2b39f0d6d45ab'
    },
    AssumeRoleProvider._resolve_static_credentials_from_profile: {
        'a470795f6ba451cf99ce7456fef24777f8087654'
    },
    AssumeRoleProvider._resolve_credentials_from_source: {
        'de41138b36bfc74d7f8a21f6002b55279d3de017'
    },
    CanonicalNameCredentialSourcer.source_credentials: {
        '602930a78e0e64e3b313a046aab5edc3bcf5c2d9'
    },
    CanonicalNameCredentialSourcer._get_provider: {
        'c028b9776383cc566be10999745b6082f458d902'
    },
    BotoProvider.load: {'e84ebfe3d6698dc4683f0f6699d4a9907c87bebb'},
    OriginalEC2Provider.load: {'dc58cd1c79d177105b183a2d20e1154e6f8f0733'},
    create_credential_resolver: {'f3501ad2330afe5e1ef4e71c7537f94885c73821'},
    get_credentials: {'ff0c735a388ac8dd7fe300a32c1e36cdf33c0f56'},
    # configprovider.py
    SmartDefaultsConfigStoreFactory.merge_smart_defaults: {
        'e320299bb739694fefe2f5df6be62cc5321d3dc5'
    },
    SmartDefaultsConfigStoreFactory.resolve_auto_mode: {
        '013fa8904b42931c69e3d8623025a1582379ba2a'
    },
    # endpoint.py
    convert_to_response_dict: {'5b7701c1f5b3cb2daa6eb307cdbdbbb2e9d33e5f'},
    Endpoint.create_request: {'37d0fbd02f91aef6c0499a2d0a725bf067c3ce8b'},
    Endpoint._send_request: {'5d40748a95c3005728e6548b402b90cb57d6f575'},
    Endpoint._get_response: {'bbf10e6e07147d50e09d7205bf0883bd673a8bf3'},
    Endpoint._do_get_response: {'5afcfe76196406903afb24e05e3dd0feeac1a23d'},
    Endpoint._needs_retry: {'f718e2ff874763a677648fe6f87cc65e4cec2792'},
    Endpoint._send: {'644c7e5bb88fecaa0b2a204411f8c7e69cc90bf1'},
    Endpoint._add_modeled_error_fields: {
        'd0390647f2d7a4a325be048dcda4dcc7f42fdd17'
    },
    EndpointCreator.create_endpoint: {
        '863e17b1299f9fda2cef5be3297d470d1bfa86ae'
    },
    # eventstream.py
    EventStream._create_raw_event_generator: {
        '1764be20b3abe19b60381756a989794de298ffbb'
    },
    EventStream.__iter__: {'8a9b454943f8ef6e81f5794d641adddd1fdd5248'},
    EventStream.get_initial_response: {
        'aed648305970c90bb5d1e31f6fe5ff12cf6a2a06'
    },
    # hooks.py
    HierarchicalEmitter._emit: {'5d9a6b1aea1323667a9310e707a9f0a006f8f6e8'},
    HierarchicalEmitter.emit_until_response: {
        '23670e04e0b09a9575c7533442bca1b2972ade82'
    },
    HierarchicalEmitter._verify_and_register: {
        '41eda968127e35e02e7120ec621240b61639e3dd'
    },
    EventAliaser.emit_until_response: {
        '0d635bf7ae5022b1fdde891cd9a91cd4c449fd49'
    },
    # paginate.py
    PageIterator.__iter__: {'a7e83728338e61ff2ca0a26c6f03c67cbabffc32'},
    PageIterator.result_key_iters: {
        'e8cd36fdc4960e08c9aa50196c4e5d1ee4e39756'
    },
    PageIterator.build_full_result: {
        '9051327d350ed5a4843c74d34be74ba2f1732e30'
    },
    ResultKeyIterator: {'3028dde4c4de6029f628f4a9d1fff36986b41591'},
    # parsers.py
    ResponseParserFactory.create_parser: {
        '5cf11c9acecd1f60a013f6facbe0f294daa3f390'
    },
    RestXMLParser._create_event_stream: {
        '0564ba55383a71cc1ba3e5be7110549d7e9992f5'
    },
    EC2QueryParser._create_event_stream: {
        '0564ba55383a71cc1ba3e5be7110549d7e9992f5'
    },
    QueryParser._create_event_stream: {
        '0564ba55383a71cc1ba3e5be7110549d7e9992f5'
    },
    JSONParser._create_event_stream: {
        '0564ba55383a71cc1ba3e5be7110549d7e9992f5'
    },
    JSONParser._do_parse: {'9c3d5832e6c55a87630128cc8b9121579ef4a708'},
    JSONParser._handle_event_stream: {
        '3cf7bb1ecff0d72bafd7e7fd6625595b4060abd6'
    },
    # NOTE: if this hits we need to change our ResponseParser impl in JSONParser
    JSONParser.parse: {'38231a2fffddfa6e91c56c2a01134459e365beb3'},
    RestJSONParser._create_event_stream: {
        '0564ba55383a71cc1ba3e5be7110549d7e9992f5'
    },
    create_parser: {'37e9f1c3b60de17f477a9b79eae8e1acaa7c89d7'},
    # response.py
    StreamingBody: {'73cb1276dfb509331b964d3d5ed69e5efa008de5'},
    get_response: {'6515f43730b546419695c26d4bc0d198fde54b10'},
    # session.py
    Session.__init__: {'d0d3b11d6feb4783d2a7399246ce02c58e2c34e7'},
    Session._register_response_parser_factory: {
        'bb8f7f3cc4d9ff9551f0875604747c4bb5030ff6'
    },
    Session.create_client: {'a179ef6d370020181d99fcb6cb1279e948d72afa'},
    Session._create_credential_resolver: {
        '87e98d201c72d06f7fbdb4ebee2dce1c09de0fb2'
    },
    Session.get_credentials: {'718da08b630569e631f93aedd65f1d9215bfc30b'},
    get_session: {'c47d588f5da9b8bde81ccc26eaef3aee19ddd901'},
    Session.get_service_data: {'3879b969c0c2b1d5b454006a1025deb4322ae804'},
    Session.get_service_model: {'1c8f93e6fb9913e859e43aea9bc2546edbea8365'},
    Session.get_available_regions: {
        '9fb4df0b7d082a74d524a4a15aaf92a2717e0358'
    },
    Session._register_smart_defaults_factory: {
        'af5fc9cf6837ed119284603ca1086e4113febec0'
    },
    # signers.py
    RequestSigner.handler: {'371909df136a0964ef7469a63d25149176c2b442'},
    RequestSigner.sign: {'d90346d5e066e89cd902c5c936f59b644ecde275'},
    RequestSigner.get_auth: {'4f8099bef30f9a72fa3bcaa1bd3d22c4fbd224a8'},
    RequestSigner.get_auth_instance: {
        'c2c34a0f44cac8819c7e9b74ca52dc82a28a1a08'
    },
    RequestSigner._choose_signer: {'eb82bd279d8c6cb7c93f7330a45544f0dda73170'},
    RequestSigner.generate_presigned_url: {
        '417682868eacc10bf4c65f3dfbdba7d20d9250db'
    },
    add_generate_presigned_url: {'5820f74ac46b004eb79e00eea1adc467bcf4defe'},
    generate_presigned_url: {'03cb4e442690f2df47f1580c66345b12764dee0e'},
    S3PostPresigner.generate_presigned_post: {
        '269efc9af054a2fd2728d5b0a27db82c48053d7f'
    },
    add_generate_presigned_post: {'e30360f2bd893fabf47f5cdb04b0de420ccd414d'},
    generate_presigned_post: {'56687f0abdf1451951cffabefa9d970256fca420'},
    add_generate_db_auth_token: {'f61014e6fac4b5c7ee7ac2d2bec15fb16fa9fbe5'},
    generate_db_auth_token: {'1f37e1e5982d8528841ce6b79f229b3e23a18959'},
    # utils.py
    ContainerMetadataFetcher.__init__: {
        '46d90a7249ba8389feb487779b0a02e6faa98e57'
    },
    ContainerMetadataFetcher.retrieve_full_uri: {
        '2c7080f7d6ee5a3dacc1b690945c045dba1b1d21'
    },
    ContainerMetadataFetcher.retrieve_uri: {
        '4ee8aa704cf0a378d68ef9a7b375a1aa8840b000'
    },
    ContainerMetadataFetcher._retrieve_credentials: {
        'b00694931af86ef1a9305ad29328030ee366cea9'
    },
    ContainerMetadataFetcher._get_response: {
        '4dc84054db957f2c1fb2fb1b01eb462bd57b1a64'
    },
    IMDSFetcher.__init__: {'e7e62b79f6a9e4cb14120e61c4516f0a61148100'},
    IMDSFetcher._get_request: {'7f8ad4724ac08300a0c55e307bfeb5abc0579d26'},
    IMDSFetcher._fetch_metadata_token: {
        '12225b35a73130632038785a8c2e6fbaaf9de1f4'
    },
    IMDSFetcher._default_retry: {'362ce5eff50bfb74e58fbdd3f44146a87958318a'},
    IMDSFetcher._is_non_ok_response: {
        '448b80545b1946ec44ff19ebca8d4993872a6281'
    },
    IMDSFetcher._is_empty: {'241b141c9c352a4ef72964f8399d46cbe9a5aebc'},
    IMDSFetcher._log_imds_response: {
        'dcbe619ce2ddb8b5015f128612d86dd8a5dd31e8'
    },
    InstanceMetadataFetcher.retrieve_iam_role_credentials: {
        '40f31ba06abb9853c2e6fea68846742bd3eda919'
    },
    InstanceMetadataFetcher._get_iam_role: {
        '80073d7adc9fb604bc6235af87241f5efc296ad7'
    },
    InstanceMetadataFetcher._get_credentials: {
        '1a64f59a3ca70b83700bd14deeac25af14100d58'
    },
    InstanceMetadataFetcher._is_invalid_json: {
        '97818b51182a2507c99876a40155adda0451dd82'
    },
    InstanceMetadataFetcher._needs_retry_for_role_name: {
        'ca9557fb8e58d03e09d77f9fb63d21afb4689b58'
    },
    InstanceMetadataFetcher._needs_retry_for_credentials: {
        'e7e5a8ce541110eb79bf98414171d3a1c137e32b'
    },
    S3RegionRedirector.redirect_from_error: {
        '3863b2c6472513b7896bfccc9dfd2567c472f441'
    },
    S3RegionRedirector.get_bucket_region: {
        'b5bbc8b010576668dc2812d657c4b48af79e8f99'
    },
    InstanceMetadataRegionFetcher.retrieve_region: {
        '0134024f0aa2d2b49ec436ea8058c1eca8fac4af'
    },
    InstanceMetadataRegionFetcher._get_region: {
        '16e8fc546958471650eef233b0fd287758293019'
    },
    IMDSRegionProvider.provide: {'09d1b70bc1dd7a37cb9ffd437acd71283b9142e9'},
    IMDSRegionProvider._get_instance_metadata_region: {
        '4631ced79cff143de5d3fdf03cd69720778f141b'
    },
    IMDSRegionProvider._create_fetcher: {
        '7031d7cdaea0244a5d860f2f8f6c013e25578123'
    },
    # waiter.py
    NormalizedOperationMethod.__call__: {
        '79723632d023739aa19c8a899bc2b814b8ab12ff'
    },
    Waiter.wait: {'735608297a2a3d4572e6705daafcf4fc8556fc03'},
    create_waiter_with_client: {'e6ea06674b6fdf9157c95757a12b3c9c35af531c'},
    # handlers.py
    inject_presigned_url_rds: {'b5d45b339686346e81b255d4e8c36e76d3fe6a78'},
    inject_presigned_url_ec2: {'48e09a5e4e95577e716be30f2d2706949261a07f'},
    parse_get_bucket_location: {'64ffbf5c6aa6ebd083f49371000fa046d0de1fc6'},
    check_for_200_error: {'ded7f3aaef7b1a5d047c4dac86692ab55cbd7a13'},
    _looks_like_special_case_error: {
        '86946722d10a72b593483fca0abf30100c609178'
    },
    # httpsession.py
    URLLib3Session: {'c72094afb3aa62db0ade9be09be72ec7a2c3d80a'},
    EndpointDiscoveryHandler.discover_endpoint: {
        'd87eff9008356a6aaa9b7078f23ba7a9ff0c7a60'
    },
    EndpointDiscoveryManager.describe_endpoint: {
        'b2f1b29177cf30f299e61b85ddec09eaa070e54e'
    },
    EndpointDiscoveryManager._refresh_current_endpoints: {
        'f8a51047c8f395d9458a904e778a3ac156a11911'
    },
    # retries/adaptive.py
    # See comments in AsyncTokenBucket: we completely replace the ClientRateLimiter
    # implementation from botocore.
    adaptive.ClientRateLimiter: {'e9d99c7921170815f0eaf5c2848765cd6ed90177'},
    adaptive.register_retry_handler: {
        '96c073719a3d5d41d1ca7ae5f7e31bbb431c75b3'
    },
    # retries/standard.py
    standard.register_retry_handler: {
        'da0ae35712211bc38938e93c4af8b7aeb999084e'
    },
    standard.RetryHandler.needs_retry: {
        '89a4148d7f4af9d2795d1d0189293528aa668b59'
    },
    standard.RetryPolicy.should_retry: {
        'b30eadcb94dadcdb90a5810cdeb2e3a0bc0c74c9'
    },
    standard.StandardRetryConditions.__init__: {
        'e17de49a447769160964a2da926b7d72544efd48'
    },
    standard.StandardRetryConditions.is_retryable: {
        '558a0f0b4d30f996e046779fe233f587611ca5c7'
    },
    standard.OrRetryChecker.is_retryable: {
        '5ef0b84b1ef3a49bc193d76a359dbd314682856b'
    },
    # retries/special.py
    special.RetryDDBChecksumError.is_retryable: {
        '6c6e0945b0989b13fd8e7d78dbfcde307a131eae'
    },
    # retries/bucket.py
    # See comments in AsyncTokenBucket: we completely replace the TokenBucket
    # implementation from botocore.
    TokenBucket: {'bddbf15ba4c2f04cb7fe04992168fa0e839047e5'},
    # awsresponse.py
    AWSResponse.content: {'1d74998e3e0abe52b52c251a1eae4971e65b1053'},
    AWSResponse.text: {'a724100ba9f6d51b333b8fe470fac46376d5044a'},
    # httpchecksum.py
    handle_checksum_body: {'4b9aeef18d816563624c66c57126d1ffa6fe1993'},
    _handle_bytes_response: {'0761c4590c6addbe8c674e40fca9f7dd375a184b'},
    AwsChunkedWrapper._make_chunk: {
        '097361692f0fd6c863a17dd695739629982ef7e4'
    },
    AwsChunkedWrapper.__iter__: {'261e26d1061655555fe3dcb2689d963e43f80fb0'},
    apply_request_checksum: {'bcc044f0655f30769994efab72b29e76d73f7e39'},
    _apply_request_trailer_checksum: {
        '55c36eaf4701a379fcdbd78d0b7a831e5023a76e'
    },
    # retryhandler.py
    retryhandler.create_retry_handler: {
        '8fee36ed89d789194585f56b8dd4f525985a5811'
    },
    retryhandler.create_checker_from_retry_config: {
        'bc43996b75ab9ffc7a4e8f20fc62805857867109'
    },
    retryhandler._create_single_checker: {
        'da29339040ab1faeaf2d80752504e4f8116686f2'
    },
    retryhandler._create_single_response_checker: {
        'dda92bb44f295a1f61750c7e1fbc176f66cb8b44'
    },
    retryhandler.RetryHandler.__call__: {
        'e599399167b1f278e4cd839170f887d60eea5bfa'
    },
    retryhandler.MaxAttemptsDecorator.__call__: {
        '24b442126f0ff730be0ae64dc7158929d4d2fca7'
    },
    retryhandler.MaxAttemptsDecorator._should_retry: {
        '8ba8bcec27974861ec35a7d91ce96db1c04833fe'
    },
    retryhandler.MultiChecker.__call__: {
        'e8302c52e1bbbb129b6f505633a4bc4ae1e5a34f'
    },
    retryhandler.CRC32Checker.__call__: {
        '882a731eaf6b0ddca68ab4032a169a0fa09a4d43'
    },
    retryhandler.CRC32Checker._check_response: {
        '3ee7afd0bb1a3bf53934d77e44f619962c52b0c9'
    },
}


_PROTOCOL_PARSER_CONTENT = {'ec2', 'query', 'json', 'rest-json', 'rest-xml'}


@pytest.mark.moto
def test_protocol_parsers():
    # Check that no new parsers have been added
    current_parsers = set(PROTOCOL_PARSERS.keys())
    assert current_parsers == _PROTOCOL_PARSER_CONTENT


# NOTE: this doesn't require moto but needs to be marked to run with coverage
@pytest.mark.moto
def test_patches():
    print(
        "Botocore version: {} aiohttp version: {}".format(
            botocore.__version__, aiohttp.__version__
        )
    )

    success = True
    for obj, digests in chain(_AIOHTTP_DIGESTS.items(), _API_DIGESTS.items()):

        try:
            source = getsource(obj)
        except TypeError:
            obj = obj.fget
            source = getsource(obj)

        digest = hashlib.sha1(source.encode('utf-8')).hexdigest()

        if digest not in digests:
            print(
                "Digest of {}:{} not found in: {}".format(
                    obj.__qualname__, digest, digests
                )
            )
            success = False

    assert success
